import base64
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from PIL import Image
from core import UserError
from media import check_attachment, validate_media, upload_path, MAX_BYTES


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.path=Path(self.directory.name)/"upload.bin"

    def tearDown(self):
        self.directory.cleanup()

    def test_picture_formats_are_preserved(self):
        for ext,format in [(".png","PNG"),(".jpg","JPEG"),(".gif","GIF"),(".webp","WEBP")]:
            with self.subTest(ext=ext):
                buffer=io.BytesIO()
                Image.new("RGB",(4,4),color="black").save(buffer,format=format)
                data=buffer.getvalue()
                self.path.write_bytes(data)
                validate_media(self.path,"picture",ext)
                self.assertEqual(self.path.read_bytes(),data)
        self.assertEqual(check_attachment("picture","photo.JPEG",100),".jpg")

    def test_disallowed_types_sizes_and_renamed_images_rejected(self):
        for kind,name,size in [("picture","x.mp4",100),("background","x.svg",100),("music","x.wav",100),("music","x.mp3",0),("background","x.mp4",MAX_BYTES["background"]+1)]:
            with self.assertRaises(UserError):
                check_attachment(kind,name,size)
        buffer=io.BytesIO()
        Image.new("RGB",(4,4)).save(buffer,format="PNG")
        self.path.write_bytes(buffer.getvalue())
        with self.assertRaises(UserError):
            validate_media(self.path,"picture",".jpg")

    def test_static_svg_with_fragment_gradient_accepted(self):
        data=b'<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"><stop offset="1" stop-color="red"/></linearGradient></defs><rect width="10" height="10" fill="url(#g)"/></svg>'
        self.path.write_bytes(data)
        validate_media(self.path,"picture",".svg")
        self.assertEqual(self.path.read_bytes(),data)

    def test_svg_scripts_external_resources_and_entities_rejected(self):
        unsafe=[
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
            '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/x"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://example.com/x)"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><body xmlns="http://www.w3.org/1999/xhtml">x</body></foreignObject></svg>',
            '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
            '<?xml-stylesheet href="https://example.com/x"?><svg xmlns="http://www.w3.org/2000/svg"/>',
        ]
        for value in unsafe:
            with self.subTest(value=value),self.assertRaises(UserError):
                self.path.write_text(value)
                validate_media(self.path,"picture",".svg")

    @unittest.skipUnless(shutil.which("ffprobe"),"Real media probing runs on the Pi")
    def test_real_mp3_and_mp4_fixtures_are_accepted(self):
        fixture=json.loads((Path(__file__).parent/"fixtures/media.json").read_text())
        for kind,ext in [("music","mp3"),("background","mp4")]:
            with self.subTest(ext=ext):
                data=base64.b64decode(fixture[ext])
                self.path.write_bytes(data)
                validate_media(self.path,kind,"."+ext)
                self.assertEqual(self.path.read_bytes(),data)

    def test_prober_has_no_credentials_and_wrong_codec_rejected(self):
        self.path.write_bytes(b"ID3"+b"0"*100)
        with patch("media.shutil.which",return_value="ffprobe"),patch("media.subprocess.run",return_value=CompletedProcess([],0,stdout=b'{"format":{"format_name":"aac"},"streams":[{"codec_name":"aac"}]}')) as run:
            with self.assertRaises(UserError):
                validate_media(self.path,"music",".mp3")
            self.assertEqual(set(run.call_args.kwargs["env"]),{"PATH","LC_ALL"})
            self.assertIn("file,crypto,data",run.call_args.args[0])

    def test_upload_path_cannot_read_another_users_files(self):
        root=Path(self.directory.name)
        self.assertEqual(upload_path(root,1,"uploads/1/x.png"),root/"uploads/1/x.png")
        for value in ["uploads/2/x.png","../../etc/passwd","uploads/1/../2/x.png"]:
            with self.assertRaises(UserError):
                upload_path(root,1,value)
