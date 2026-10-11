/* Profile text lives in settings/. Media and advanced options live in index.html. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const svg = (content, fill = "none") => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="${fill}" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${content}</svg>`;
  const icons = {
    premium: svg('<path d="m3 8 4-5h10l4 5-9 13Z"/><path d="M3 8h18M7 3l5 18 5-18M7 3l5 5 5-5"/>'),
    verified: svg('<path d="m12 2 2.4 1.5 2.8.2 1.2 2.6 2.2 1.8-.4 2.9.4 2.9-2.2 1.8-1.2 2.6-2.8.2L12 20l-2.4-1.5-2.8-.2-1.2-2.6-2.2-1.8.4-2.9-.4-2.9 2.2-1.8 1.2-2.6 2.8-.2Z" fill="currentColor" stroke="none"/><path d="m8 11 2.5 2.5L16 8" stroke="#17181b" stroke-width="2.2"/>'),
    staff: svg('<path d="M12 2 4 5v6c0 5 8 10 8 10s8-5 8-10V5Z"/><path d="m8.5 11 2.5 2.5 4.5-5"/>'),
    og: svg('<path d="m12 2 3.1 6.3 7 .9-5.1 5 .9 7-5.9-3.3-5.9 3.3.9-7L2 9.2l7-.9Z" fill="currentColor" stroke="none"/>'),
    donor: svg('<path d="M12 3c-2 4-7 7-7 12a7 7 0 0 0 14 0c0-3-1.5-5-3-7 0 4-2 4-2 4s1-5-2-9Z" fill="currentColor" stroke="none"/>'),
    booster: svg('<path d="m13 2-9 12h7l-1 8 10-13h-7Z" fill="currentColor" stroke="none"/>'),
    developer: svg('<path d="m8 6-6 6 6 6m8-12 6 6-6 6M14 3l-4 18"/>'),
    owner: svg('<path d="m3 6 4.5 4L12 3l4.5 7L21 6l-2 12H5ZM5 21h14"/>'),
    gift: svg('<path d="M3 9h18v4H3zM5 13v8h14v-8M12 9v12"/><path d="M12 9H8a3 3 0 1 1 3-3Zm0 0h4a3 3 0 1 0-3-3Z"/>'),
    bug: svg('<path d="M8 8a4 4 0 0 1 8 0v8a4 4 0 0 1-8 0ZM12 9v11M7 4l2 2m8-2-2 2M3 9l5 2m13-2-5 2M3 15h5m13 0h-5M5 21l4-3m10 3-4-3"/>'),
    heart: svg('<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" fill="currentColor" stroke="none"/>'),
    "image-host": svg('<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>'),
    discord: svg('<path d="M19.7 5.5A18 18 0 0 0 15.3 4l-.5 1a16 16 0 0 0-5.6 0l-.5-1a18 18 0 0 0-4.4 1.5C1.5 9.5.7 13.4 1.1 17.2a18 18 0 0 0 5.4 2.7l1.1-1.7-1.7-.9.4-.3a13.6 13.6 0 0 0 11.4 0l.4.3-1.7.9 1.1 1.7a18 18 0 0 0 5.4-2.7c.5-4.4-.8-8.2-3.2-11.7ZM8.3 14.9c-1.1 0-1.9-1-1.9-2.2s.8-2.2 1.9-2.2 1.9 1 1.9 2.2-.8 2.2-1.9 2.2Zm7.4 0c-1.1 0-1.9-1-1.9-2.2s.8-2.2 1.9-2.2 1.9 1 1.9 2.2-.8 2.2-1.9 2.2Z" stroke="none" fill="currentColor"/>'),
    github: svg('<path d="M12 .8a11.3 11.3 0 0 0-3.6 22c.6.1.8-.2.8-.6v-2.1c-3.3.7-4-1.4-4-1.4-.6-1.4-1.4-1.8-1.4-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.7 2.6 1.2 3.3.9.1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.6 0-1.2.4-2.2 1.2-3-.1-.3-.5-1.5.1-3 0 0 1-.3 3.1 1.2a11 11 0 0 1 6.2 0c2.2-1.5 3.1-1.2 3.1-1.2.6 1.5.2 2.7.1 3 .8.8 1.2 1.8 1.2 3 0 4.4-2.7 5.3-5.3 5.6.4.4.8 1.1.8 2.1v3.4c0 .4.2.7.8.6A11.3 11.3 0 0 0 12 .8Z" stroke="none" fill="currentColor"/>'),
    spotify: svg('<circle cx="12" cy="12" r="10.7" fill="currentColor" stroke="none"/><path d="M5.8 9.3c4.4-1.3 9.1-.8 12.5 1.1M6.6 12.5c3.6-1.1 7.5-.6 10.6.9M7.4 15.4c3-.8 5.9-.4 8.5.8" stroke="#17181b" stroke-width="1.6"/>'),
    youtube: svg('<path d="M22.5 6.7a2.8 2.8 0 0 0-2-2C18.8 4.2 12 4.2 12 4.2s-6.8 0-8.5.5a2.8 2.8 0 0 0-2 2C1 8.4 1 12 1 12s0 3.6.5 5.3a2.8 2.8 0 0 0 2 2c1.7.5 8.5.5 8.5.5s6.8 0 8.5-.5a2.8 2.8 0 0 0 2-2C23 15.6 23 12 23 12s0-3.6-.5-5.3Z" fill="currentColor" stroke="none"/><path d="m9.8 8.5 5.8 3.5-5.8 3.5Z" fill="#17181b" stroke="none"/>'),
    instagram: svg('<rect x="3" y="3" width="18" height="18" rx="5" stroke-width="2.3"/><circle cx="12" cy="12" r="4.3" stroke-width="2.3"/><circle cx="17.6" cy="6.5" r="1.25" fill="currentColor" stroke="none"/>'),
    globe: svg('<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a18 18 0 0 1 0 20 18 18 0 0 1 0-20Z"/>'),
    x: svg('<path d="M4 3h4.5L20 21h-4.5ZM20 3 4 21"/>'),
    tiktok: svg('<path d="M15 3v12a6 6 0 1 1-6-6v4a2 2 0 1 0 2 2V3Zm0 0c.4 3 2.7 5 6 5v4a10 10 0 0 1-6-2" fill="currentColor" stroke="none"/>'),
    twitch: svg('<path d="M4 2 2 6v15h5v3l4-3h4l7-7V2ZM20 13l-4 4h-5l-3 3v-3H5V4h15ZM10 7h2v6h-2Zm5 0h2v6h-2Z" fill="currentColor" stroke="none"/>'),
    telegram: svg('<path d="m21.4 3.3-3.7 17.4c-.3 1.2-1 1.5-2 .9l-5.6-4.1-2.7 2.6c-.3.3-.6.5-1.1.5l.4-5.6L17 5.7c.5-.4-.1-.7-.7-.3L3.6 13.5.2 12.4c-1.1-.3-1.1-1.1.3-1.7L20.1 3c.9-.3 1.6.2 1.3.3Z" fill="currentColor" stroke="none"/>'),
    mail: svg('<rect x="2" y="4" width="20" height="16" rx="3"/><path d="m2 6 10 7L22 6"/>'),
    eye: svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'),
    pin: svg('<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>'),
    volume: svg('<path d="m11 4-6 4H2v8h3l6 4ZM15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>'),
    muted: svg('<path d="m11 4-6 4H2v8h3l6 4ZM17 9l5 6m0-6-5 6"/>'),
    pause: svg('<path d="M8 5v14M16 5v14" stroke-width="3.2"/>'),
    play: svg('<path d="m8 4 12 8-12 8Z" fill="currentColor" stroke="none"/>'),
  };
  icons.star = icons.og;

  const badgeLabels = {
    developer: "Developer", owner: "Owner", premium: "Premium", verified: "Verified",
    staff: "Staff", og: "OG", donor: "Donor", booster: "Server Booster", gift: "Gifter",
    bug: "Bug Hunter", star: "Star", heart: "Heart", "image-host": "Image Host",
  };
  const platforms = {
    GITHUB: { icon: "github", label: "GitHub", prefix: "https://github.com/" },
    YOUTUBE: { icon: "youtube", label: "YouTube", prefix: "https://www.youtube.com/@" },
    INSTAGRAM: { icon: "instagram", label: "Instagram", prefix: "https://www.instagram.com/" },
    SPOTIFY: { icon: "spotify", label: "Spotify", prefix: "https://open.spotify.com/user/" },
    TWITCH: { icon: "twitch", label: "Twitch", prefix: "https://www.twitch.tv/" },
    TIKTOK: { icon: "tiktok", label: "TikTok", prefix: "https://www.tiktok.com/@" },
    X: { icon: "x", label: "X", prefix: "https://x.com/" },
    TWITTER: { icon: "x", label: "X", prefix: "https://x.com/" },
    TELEGRAM: { icon: "telegram", label: "Telegram", prefix: "https://t.me/" },
    DISCORD: { icon: "discord", label: "Discord" },
    WEBSITE: { icon: "globe", label: "Website" },
    EMAIL: { icon: "mail", label: "Email" },
    MAIL: { icon: "mail", label: "Email" },
  };

  let badges = BADGES;
  let connections = PROFILE.links || [];
  let names = [PROFILE.fallbackName || "jvbj"];
  let bios = (Array.isArray(PROFILE.bio) ? PROFILE.bio : [PROFILE.bio]).map((text) => String(text || "")).filter(Boolean);

  let displayName = names[0];
  let entered = false;
  let motionPaused = reducedMotion.matches;
  let muted = !!PROFILE.startMuted;
  let volume = Math.max(0, Math.min(1, Number(PROFILE.volume) || 0));
  let stopTyping = () => {};
  let presenceTimer;
  let presenceController;
  let toastTimer;
  const video = $("backgroundVideo");
  const audio = new Audio();
  audio.loop = true;
  audio.preload = "none";

  function safeURL(value, allowMail = false) {
    if (typeof value !== "string" || !value.trim()) return "";
    try {
      const url = new URL(value, document.baseURI);
      return ["https:", "http:", ...(allowMail ? ["mailto:"] : [])].includes(url.protocol) ? url.href : "";
    } catch { return ""; }
  }

  function addIcon(element, settings) {
    const imageURL = safeURL(settings.image);
    if (imageURL) {
      const img = document.createElement("img");
      img.src = imageURL;
      img.alt = "";
      img.addEventListener("error", () => { element.innerHTML = icons.star; }, { once: true });
      element.append(img);
    } else {
      element.innerHTML = icons[settings.icon] || icons.star;
    }
  }

  function renderBadges() {
    $("badges").replaceChildren();
    for (const badge of badges) {
      if (badge.hidden) continue;
      const url = safeURL(badge.url);
      const el = document.createElement(url ? "a" : "span");
      el.className = "badge";
      el.dataset.tooltip = badge.label || "Badge";
      el.setAttribute("aria-label", badge.label || "Badge");
      if (url) { el.href = url; el.target = "_blank"; el.rel = "noopener noreferrer"; }
      else { el.tabIndex = 0; el.setAttribute("role", "img"); }
      if (badge.color && CSS.supports("color", badge.color)) el.style.setProperty("--badge-color", badge.color);
      addIcon(el, badge);
      $("badges").append(el);
    }
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    $("toast").textContent = message;
    $("toast").classList.add("visible");
    toastTimer = setTimeout(() => $("toast").classList.remove("visible"), 2400);
  }

  async function copyText(text, label) {
    try {
      await navigator.clipboard.writeText(text);
      showToast(`${label} copied`);
    } catch {
      const input = document.createElement("textarea");
      input.value = text;
      input.style.cssText = "position:fixed;opacity:0;pointer-events:none";
      document.body.append(input);
      input.select();
      const copied = document.execCommand("copy");
      input.remove();
      showToast(copied ? `${label} copied` : text);
    }
  }

  function renderLinks() {
    $("socialLinks").replaceChildren();
    for (const link of connections) {
      const url = safeURL(link.url, true);
      if (link.hidden || (!url && !link.copy)) continue;
      const el = document.createElement(link.copy ? "button" : "a");
      el.className = "social-link";
      const label = link.label || link.icon || "Link";
      el.dataset.tooltip = label;
      el.setAttribute("aria-label", link.copy ? `Copy ${label}` : label);
      if (link.copy) { el.type = "button"; el.addEventListener("click", () => copyText(String(link.copy), label)); }
      else { el.href = url; el.target = "_blank"; el.rel = "noopener noreferrer"; }
      addIcon(el, link);
      $("socialLinks").append(el);
    }
  }

  function setName(name) {
    displayName = name;
    $("nameText").textContent = name;
    $("nameCursor").hidden = !PROFILE.typewriter || reducedMotion.matches;
    $("avatar").alt = `${name}'s profile picture`;
    document.title = `@${name}`;
    document.querySelector('meta[property="og:title"]').content = name;
    if (!PROFILE.discord?.username && !PROFILE.discord?.userId) $("discordUsername").textContent = name;
  }

  async function readSetting(path) {
    if (!path) return null;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(path, { cache: "no-store", signal: controller.signal });
      if (!response.ok || response.headers.get("content-type")?.includes("text/html")) return null;
      return (await response.text()).replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
    } catch { return null; }
    finally { clearTimeout(timeout); }
  }

  function settingLines(text) {
    return text.split("\n").map((line) => line.trim()).filter((line) => line && !line.startsWith("#"));
  }

  function settingParagraphs(text) {
    return text.split(/\n[\t ]*\n(?:[\t ]*\n)*/).map((entry) => entry.trim()).filter(Boolean);
  }

  function parseBadges(text) {
    return settingLines(text).flatMap((line) => {
      const id = line.toLowerCase();
      const custom = BADGES.find((badge) => String(badge.id || badge.icon || "").toLowerCase() === id);
      if (custom) return [custom];
      if (Object.hasOwn(badgeLabels, id)) return [{ icon: id, label: badgeLabels[id] }];
      return [];
    });
  }

  function parseConnections(text) {
    return settingLines(text).flatMap((line) => {
      const separator = line.indexOf("=");
      if (separator < 1) return [];
      const key = line.slice(0, separator).trim().toUpperCase();
      const value = line.slice(separator + 1).trim();
      if (!Object.hasOwn(platforms, key) || !value) return [];
      const platform = platforms[key];
      if (/^https?:\/\//i.test(value)) {
        const url = safeURL(value);
        return url ? [{ icon: platform.icon, label: platform.label, url }] : [];
      }
      // Handles are plain text; other URI schemes are not profile links.
      if (/^[a-z][a-z\d+.-]*:/i.test(value)) return [];
      if (key === "DISCORD") {
        return /^\d{17,20}$/.test(value)
          ? [{ ...platform, url: `https://discord.com/users/${value}` }]
          : [{ ...platform, copy: value.replace(/^@/, "") }];
      }
      if (key === "EMAIL" || key === "MAIL") {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? [{ ...platform, url: `mailto:${value}` }] : [];
      }
      if (key === "WEBSITE") {
        const url = !/\s/.test(value) && safeURL(`https://${value}`);
        return url ? [{ ...platform, url }] : [];
      }
      const handle = value.replace(/^@/, "");
      if (!handle || /[\s/\\?#]/.test(handle)) return [];
      return [{ icon: platform.icon, label: platform.label, url: platform.prefix + encodeURIComponent(handle) }];
    });
  }

  function renderBio() {
    $("bio").hidden = !bios.length;
    $("bioText").textContent = bios[0] || "";
    $("typeCursor").hidden = !PROFILE.typewriter || reducedMotion.matches || !bios.length;
    document.querySelector('meta[name="description"]').content = bios[0] || displayName;
    document.querySelector('meta[property="og:description"]').content = bios[0] || displayName;
  }

  async function loadSettings() {
    const [namesText, biosText, badgesText, connectionsText] = await Promise.all([
      readSetting(PROFILE.namesFile), readSetting(PROFILE.biosFile),
      readSetting(PROFILE.badgesFile), readSetting(PROFILE.connectionsFile),
    ]);
    if (namesText !== null) {
      names = settingParagraphs(namesText);
      if (!names.length) names = [PROFILE.fallbackName || "jvbj"];
      setName(names[0]);
    }
    if (biosText !== null) bios = settingParagraphs(biosText);
    // A present, empty file is intentional: it clears that section.
    if (badgesText !== null) badges = parseBadges(badgesText);
    if (connectionsText !== null) connections = parseConnections(connectionsText);
    renderBio();
    renderBadges();
    renderLinks();
    if (entered) startTypewriters();
  }

  function typewrite(container, text, cursor, entries) {
    let timer;
    container.removeAttribute("aria-label");
    text.removeAttribute("aria-hidden");
    cursor.hidden = !PROFILE.typewriter || reducedMotion.matches || !entries.length;
    if (!PROFILE.typewriter || reducedMotion.matches || !entries.length) {
      text.textContent = entries[0] || "";
      return () => {};
    }
    container.setAttribute("aria-label", entries.join("\n\n"));
    text.setAttribute("aria-hidden", "true");
    let index = 0;
    let chars = Array.from(entries[index]);
    let length = 0;
    let deleting = false;
    function tick() {
      if (document.hidden) { timer = setTimeout(tick, 500); return; }
      length += deleting ? -1 : 1;
      text.textContent = chars.slice(0, length).join("");
      let delay = deleting ? 45 : 90;
      if (!deleting && length === chars.length) {
        if (entries.length === 1) return;
        deleting = true;
        delay = 2200;
      } else if (deleting && length === 0) {
        deleting = false;
        index = (index + 1) % entries.length;
        chars = Array.from(entries[index]);
        delay = 350;
      }
      timer = setTimeout(tick, delay);
    }
    text.textContent = "";
    tick();
    return () => clearTimeout(timer);
  }

  function startTypewriters() {
    stopTyping();
    const stopName = typewrite($("displayName"), $("nameText"), $("nameCursor"), names);
    const stopBio = typewrite($("bio"), $("bioText"), $("typeCursor"), bios);
    stopTyping = () => { stopName(); stopBio(); };
  }

  function setPresence(status, activity) {
    const validStatus = ["online", "idle", "dnd", "offline"].includes(status) ? status : "offline";
    const labels = { online: "Online", idle: "Idle", dnd: "Do not disturb", offline: "Offline" };
    $("discordStatus").className = `status-dot ${validStatus}`;
    $("discordStatus").setAttribute("aria-label", labels[validStatus]);
    $("discordActivity").textContent = activity || labels[validStatus];
  }

  async function refreshPresence() {
    const id = PROFILE.discord?.userId;
    if (!PROFILE.discord?.enabled || !/^\d{17,20}$/.test(id || "") || document.hidden) return;
    presenceController?.abort();
    presenceController = new AbortController();
    const timeout = setTimeout(() => presenceController.abort(), 6000);
    try {
      const response = await fetch(`https://api.lanyard.rest/v1/users/${id}`, { signal: presenceController.signal });
      if (!response.ok) return;
      const payload = await response.json();
      if (!payload.success || !payload.data) return;
      const data = payload.data;
      const user = data.discord_user;
      if (user) {
        $("discordUsername").textContent = PROFILE.discord.username || user.global_name || user.username || displayName;
        if (user.avatar && !PROFILE.discord.avatar) {
          const extension = user.avatar.startsWith("a_") ? "gif" : "webp";
          $("discordAvatar").src = `https://cdn.discordapp.com/avatars/${id}/${user.avatar}.${extension}?size=128`;
        }
      }
      const custom = data.activities?.find((activity) => activity.type === 4);
      const playing = data.activities?.find((activity) => activity.type === 0);
      const activity = data.listening_to_spotify && data.spotify ? `Listening to ${data.spotify.song}` : custom?.state || (playing ? `Playing ${playing.name}` : "");
      setPresence(data.discord_status, activity);
    } catch { /* Retain configured presence if the optional API is unavailable. */ }
    finally { clearTimeout(timeout); }
  }

  function renderDiscord() {
    const config = PROFILE.discord;
    $("discordPresence").hidden = !config?.enabled;
    if (!config?.enabled) return;
    $("discordUsername").textContent = config.username || displayName;
    $("discordAvatar").src = safeURL(config.avatar || PROFILE.avatar) || "assets/profile.png";
    $("discordLogo").innerHTML = icons.discord;
    setPresence(config.status, config.activity);
    const url = safeURL(config.url || (/^\d{17,20}$/.test(config.userId || "") ? `https://discord.com/users/${config.userId}` : ""));
    if (url) {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.className = "discord-presence linked";
      anchor.id = "discordPresence";
      anchor.setAttribute("aria-label", "Discord profile");
      anchor.append(...$("discordPresence").childNodes);
      $("discordPresence").replaceWith(anchor);
    }
    refreshPresence();
    if (/^\d{17,20}$/.test(config.userId || "")) presenceTimer = setInterval(refreshPresence, 30000);
  }

  function updateVolume() {
    for (const media of [video, audio]) { media.volume = volume; media.muted = muted || volume === 0; }
    const isMuted = muted || volume === 0;
    $("muteButton").innerHTML = isMuted ? icons.muted : icons.volume;
    $("muteButton").setAttribute("aria-label", isMuted ? "Unmute audio" : "Mute audio");
    $("muteButton").setAttribute("aria-pressed", String(isMuted));
    $("volume").value = String(Math.round(volume * 100));
    $("volume").setAttribute("aria-valuetext", `${Math.round(volume * 100)} percent`);
  }

  function playMedia(media) { media.play().catch(() => { /* Unsupported or unavailable media keeps the static fallback. */ }); }

  function updateMotion() {
    document.body.classList.toggle("motion-paused", motionPaused);
    $("motionButton").innerHTML = motionPaused ? icons.play : icons.pause;
    $("motionButton").setAttribute("aria-label", motionPaused ? "Play background" : "Pause background");
    $("motionButton").setAttribute("aria-pressed", String(motionPaused));
    if (motionPaused) video.pause();
    else if (entered && video.getAttribute("src") && !document.hidden) playMedia(video);
  }

  function makeParticles() {
    if (!PROFILE.particles || reducedMotion.matches) return;
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < 35; i++) {
      const particle = document.createElement("i");
      particle.className = "particle";
      const values = { x: `${Math.random() * 100}%`, size: `${1 + Math.random() * 2}px`, duration: `${12 + Math.random() * 18}s`, delay: `${-Math.random() * 30}s`, opacity: `${0.1 + Math.random() * 0.3}`, drift: `${Math.random() * 100 - 50}px` };
      for (const [key, value] of Object.entries(values)) particle.style.setProperty(`--${key}`, value);
      fragment.append(particle);
    }
    $("particles").append(fragment);
  }

  function enter() {
    if (entered) return;
    entered = true;
    document.body.classList.add("entered");
    $("page").inert = false;
    $("page").removeAttribute("aria-hidden");
    $("entryGate").tabIndex = -1;
    updateVolume();
    updateMotion();
    if (PROFILE.audio && audio.getAttribute("src")) playMedia(audio);
    startTypewriters();
    const name = $("displayName");
    name.tabIndex = -1;
    name.focus({ preventScroll: true });
  }

  const root = document.documentElement;
  if (CSS.supports("color", PROFILE.accent)) root.style.setProperty("--accent", PROFILE.accent);
  root.style.setProperty("--card-opacity", String(Math.max(0, Math.min(1, Number(PROFILE.cardOpacity) || 0))));
  root.style.setProperty("--card-blur", `${Math.max(0, Number(PROFILE.cardBlur) || 0)}px`);
  root.style.setProperty("--card-radius", `${Math.max(0, Number(PROFILE.cardRadius) || 0)}px`);
  $("enterText").textContent = PROFILE.enterText || "click to enter...";
  $("avatar").src = safeURL(PROFILE.avatar) || "assets/profile.png";
  document.querySelector('link[rel="icon"]').href = $("avatar").src;
  for (const id of ["avatar", "discordAvatar"]) $(id).addEventListener("error", (event) => { event.currentTarget.src = "assets/avatar.svg"; }, { once: true });
  const imageURL = safeURL(PROFILE.backgroundImage);
  if (imageURL) { $("backgroundImage").style.backgroundImage = `url(${JSON.stringify(imageURL)})`; video.poster = imageURL; }
  const videoURL = safeURL(PROFILE.backgroundVideo);
  if (videoURL) {
    video.src = videoURL;
    video.addEventListener("loadeddata", () => video.classList.add("ready"), { once: true });
    video.addEventListener("error", () => { video.classList.remove("ready"); video.removeAttribute("src"); }, { once: true });
  } else { video.hidden = true; }
  const audioURL = safeURL(PROFILE.audio);
  if (audioURL) audio.src = audioURL;
  if (PROFILE.location) {
    $("location").hidden = false;
    $("location").innerHTML = icons.pin;
    $("location").append(document.createTextNode(String(PROFILE.location)));
  }
  if (PROFILE.uid) $("displayName").title = `UID ${PROFILE.uid}`;
  $("viewsIcon").innerHTML = icons.eye;
  $("profileViews").hidden = PROFILE.views === null || PROFILE.views === undefined;
  $("viewsCount").textContent = Number.isFinite(Number(PROFILE.views)) ? Math.max(0, Number(PROFILE.views)).toLocaleString() : "0";
  $("profileViews").setAttribute("aria-label", `${$("viewsCount").textContent} profile views`);

  setName(displayName);
  renderBio();
  renderBadges();
  renderLinks();
  renderDiscord();
  loadSettings();
  makeParticles();
  // Keep all media muted until the visitor's entry gesture.
  $("muteButton").innerHTML = icons.volume;
  updateMotion();
  $("entryGate").addEventListener("click", enter);
  $("muteButton").addEventListener("click", () => { muted = !(muted || volume === 0); if (!muted && volume === 0) volume = Math.max(Number(PROFILE.volume) || 0.35, 0.05); updateVolume(); });
  $("volume").addEventListener("input", (event) => { volume = Number(event.target.value) / 100; muted = volume === 0; updateVolume(); });
  $("motionButton").addEventListener("click", () => { motionPaused = !motionPaused; updateMotion(); });

  if (PROFILE.tilt && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    const card = $("profileCard");
    card.addEventListener("pointermove", (event) => {
      if (reducedMotion.matches) return;
      const rect = card.getBoundingClientRect();
      card.style.setProperty("--tilt-x", `${((event.clientY - rect.top) / rect.height - 0.5) * -5}deg`);
      card.style.setProperty("--tilt-y", `${((event.clientX - rect.left) / rect.width - 0.5) * 5}deg`);
    });
    card.addEventListener("pointerleave", () => { card.style.setProperty("--tilt-x", "0deg"); card.style.setProperty("--tilt-y", "0deg"); });
  }

  reducedMotion.addEventListener("change", () => {
    motionPaused = reducedMotion.matches;
    updateMotion();
    $("particles").replaceChildren();
    makeParticles();
    if (entered) startTypewriters();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { video.pause(); audio.pause(); }
    else if (entered) { updateMotion(); if (audioURL) playMedia(audio); refreshPresence(); }
  });
  window.addEventListener("pagehide", () => { stopTyping(); clearInterval(presenceTimer); presenceController?.abort(); });
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    if (entered) { updateMotion(); startTypewriters(); if (audioURL) playMedia(audio); }
    refreshPresence();
    if (PROFILE.discord?.enabled && /^\d{17,20}$/.test(PROFILE.discord.userId || "")) presenceTimer = setInterval(refreshPresence, 30000);
  });
})();
