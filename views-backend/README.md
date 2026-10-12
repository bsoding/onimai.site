# Onimai profile views

This Flask/Gunicorn service runs on the Pi as `onimai-views`, behind a dedicated Cloudflare Tunnel at `api.onimai.site`. It listens only on `/run/onimai-views/api.sock`. The socket is accessible to the backend and the dedicated `onimai-tunnel` account; no API TCP port is exposed to the LAN or Internet.

The shared profile script loads the current total and requests a one-use visit ticket after the visitor clicks to enter. After at least two visible seconds, it redeems the ticket. Analytics failures do not block the profile.

- One counted visit per profile and IPv4 address or IPv6 /64 subnet per rolling 24 hours.
- Persistent limits: 120 API requests/minute, 12 writes/minute, and 30 counted profiles/day per IP/subnet. Limits survive service restarts and failed claims also consume limits.
- Tickets are random, stored hashed, bound to the profile and trusted IP/subnet, expire after two minutes, and cannot be replayed. Client-supplied counts, IPs, and extra body fields are rejected.
- The API trusts only `CF-Connecting-IP` received on the protected tunnel socket. `X-Forwarded-For` and `X-Real-IP` are ignored. Missing or malformed Cloudflare headers, private addresses and Worker subrequests are rejected.
- Writes require the Onimai website Origin, JSON, and a small body. The registry restricts requests to existing profiles. The bot refreshes it after publication and every five minutes.
- No raw visitor IPs, browser identifiers, cookies or user IDs are stored. Addresses are keyed with a private server HMAC secret. Visitor deduplication records expire after 24 hours.

Origin headers and client JavaScript are not authentication. An attacker can mimic a browser, visit once from each IP, or rotate proxies. These controls block simple header forgery, replays and repeated inflation; no public anonymous counter can guarantee real unique humans. Stronger human verification would require an additional service such as server-validated Turnstile.

## Tunnel authorization

For overnight setup, the private LAN link at `http://192.168.86.36:8877/setup/<random token>` remains usable until configuration finishes. Open it on your home Wi-Fi. It generates a fresh Cloudflare approval when clicked, so a short-lived login URL is not left to expire overnight. The link service accepts only the local subnet and an unguessable capability, does not log that URL, and exposes no view counting or credential download routes. A path unit starts the tunnel after the configuration is finalized.

`onimai-tunnel-setup.service` runs `cloudflared tunnel login` under the isolated tunnel account. Its private `/var/lib/onimai-tunnel/setup-status.json` contains the approval URL. Open that URL, select **onimai.site**, and authorize. The job verifies the domain, creates only `onimai-profile-views`, adds `api.onimai.site` without overwriting existing DNS, validates its private-socket ingress, deletes the temporary account management certificate, and starts `onimai-tunnel.service`. Existing tunnels and the apex website are not modified.

The backend database and secret are under `/var/lib/onimai-views` and `/etc/onimai-views/environment`. Preserve both during updates. Losing the secret changes visitor identities; losing the database resets totals.

```sh
sudo systemctl status onimai-views onimai-tunnel
sudo cat /var/lib/onimai-tunnel/setup-status.json
sudo journalctl -u onimai-views -u onimai-tunnel --no-pager
```

If authorization expires, restart `onimai-tunnel-setup.service` and use the newly generated URL. Unit and database ownership keep tunnel credentials separate from the analytics process.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests cover replay, expiration, IP binding, forwarded-header spoofing, IPv6 rotation, daily deduplication, concurrent claims, rate limits across restarts, the daily cap, body/origin/host validation and private hashed storage. Production checks verify the Unix socket permissions, deny access to an unprivileged account, and confirm the service has no TCP listener.
