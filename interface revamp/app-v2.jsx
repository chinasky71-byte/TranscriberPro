/* global React, ReactDOM */
const { useState, useEffect, useRef, useCallback, useMemo } = React;

// ───────────────────────────────────────────────────────────
// ICONS
// ───────────────────────────────────────────────────────────
const Icon = ({ d, size = 16, stroke = 1.5, fill = "none", style }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor"
       strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={style}>
    {typeof d === "string" ? <path d={d} /> : d}
  </svg>
);

const ICONS = {
  play:    "M7 5l12 7-12 7V5z",
  stop:    <rect x="6" y="6" width="12" height="12" rx="1.5" />,
  plus:    "M12 5v14M5 12h14",
  folder:  "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z",
  trash:   "M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-7 0v13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V7",
  settings:"M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
  globe:   "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0 0c2.5-2.5 4-6 4-9s-1.5-6.5-4-9m0 18c-2.5-2.5-4-6-4-9s1.5-6.5 4-9M3 12h18",
  target:  <g><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></g>,
  wrench:  "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.7 2.7-2-2 2.7-2.7z",
  upload:  "M12 19V5m0 0l-6 6m6-6l6 6",
  download:"M12 5v14m0 0l-6-6m6 6l6-6",
  film:    <g><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 8h18M3 16h18M8 4v16M16 4v16"/></g>,
  search:  <g><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></g>,
  power:   "M12 3v8M5.6 6.6a8 8 0 1 0 12.8 0",
  cpu:     <g><rect x="5" y="5" width="14" height="14" rx="1.5"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/></g>,
  chip:    <g><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/></g>,
  gpu:     <g><rect x="2" y="6" width="20" height="12" rx="1.5"/><circle cx="8" cy="12" r="2.5"/><circle cx="16" cy="12" r="2.5"/></g>,
  hardDrive:<g><path d="M3 12h18"/><path d="M5 12V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v6M5 12v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/><circle cx="7" cy="16" r="0.5" fill="currentColor"/></g>,
  arrowDown: "M12 5v14m-6-6l6 6 6-6",
  arrowUp:   "M12 19V5m6 6l-6-6-6 6",
  check:   "M5 12l4 4L19 7",
  x:       "M6 6l12 12M18 6L6 18",
  chevDown:"M6 9l6 6 6-6",
  chevRight:"M9 6l6 6-6 6",
  grip:    <g><circle cx="9" cy="6" r="1" fill="currentColor"/><circle cx="15" cy="6" r="1" fill="currentColor"/><circle cx="9" cy="12" r="1" fill="currentColor"/><circle cx="15" cy="12" r="1" fill="currentColor"/><circle cx="9" cy="18" r="1" fill="currentColor"/><circle cx="15" cy="18" r="1" fill="currentColor"/></g>,
  list:    "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  clock:   <g><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></g>,
  alert:   "M12 9v4m0 4h.01M10.3 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 17l.9 2.1L22 20l-2.1.9L19 23l-.9-2.1L16 20l2.1-.9L19 17z",
  user:    <g><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></g>,
  mic:     <g><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8"/></g>,
  language:"M5 8h12M9 4v4M11 18l4-9 4 9M12 16h6M3 20s2-1 3-3M7 4l3 3",
  caption: <g><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 11h2M7 15h4M13 11h4M13 15h2"/></g>,
  history: <g><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></g>,
  external:"M14 4h6v6M10 14L20 4M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6",
  cloud:   "M7 18a5 5 0 1 1 .8-9.94 6 6 0 0 1 11.4 2.5A4.5 4.5 0 0 1 18 18z",
  female:  <g><circle cx="12" cy="9" r="5"/><path d="M12 14v7M9 18h6"/></g>,
  volume:  <g><path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14"/></g>,
};

// ───────────────────────────────────────────────────────────
// MOCK DATA
// ───────────────────────────────────────────────────────────
const SAMPLE_FILES = [
  { name: "The Northman (2022).mkv",          size: "8.4 GB",  status: "processing", progress: 67, lang: "ENG → ITA" },
  { name: "Dune Part Two (2024).mp4",         size: "12.1 GB", status: "queued",     progress: 0,  lang: "ENG → ITA" },
  { name: "Past Lives (2023).mkv",            size: "3.2 GB",  status: "queued",     progress: 0,  lang: "KOR → ITA" },
  { name: "Anatomy of a Fall (2023).mkv",     size: "4.8 GB",  status: "queued",     progress: 0,  lang: "FRA → ITA" },
  { name: "The Zone of Interest (2023).mp4",  size: "2.9 GB",  status: "queued",     progress: 0,  lang: "DEU → ITA" },
  { name: "Perfect Days (2023).mkv",          size: "5.1 GB",  status: "queued",     progress: 0,  lang: "JPN → ITA" },
];

const SAMPLE_HISTORY = [
  { name: "Poor Things (2023).mp4",            date: "Oggi · 13:42",      lang: "ENG → ITA", duration: "08m 12s", size: "7.6 GB", path: "/media/Film/Poor.Things.2023/Poor.Things.it.srt" },
  { name: "La Chimera (2023).mkv",             date: "Oggi · 11:08",      lang: "ITA → ITA", duration: "06m 47s", size: "4.2 GB", path: "/media/Film/La.Chimera.2023/La.Chimera.it.srt" },
  { name: "Killers of the Flower Moon.mkv",    date: "Ieri · 22:14",      lang: "ENG → ITA", duration: "14m 03s", size: "11.2 GB",path: "/media/Film/Killers/Killers.it.srt" },
  { name: "Oppenheimer (2023).mp4",            date: "Ieri · 19:30",      lang: "ENG → ITA", duration: "12m 51s", size: "9.8 GB", path: "/media/Film/Oppenheimer/Oppenheimer.it.srt" },
  { name: "Anatomia di una caduta.mkv",        date: "30 apr · 16:22",    lang: "FRA → ITA", duration: "09m 17s", size: "5.0 GB", path: "/media/Film/Anatomia/Anatomia.it.srt" },
  { name: "Society of the Snow.mp4",           date: "29 apr · 21:55",    lang: "SPA → ITA", duration: "11m 32s", size: "6.7 GB", path: "/media/Film/Snow/Snow.it.srt" },
  { name: "Past Lives (2023).mkv",             date: "28 apr · 14:08",    lang: "KOR → ITA", duration: "07m 21s", size: "3.2 GB", path: "/media/Film/Past.Lives/Past.Lives.it.srt" },
  { name: "20 Days in Mariupol.mp4",           date: "27 apr · 09:12",    lang: "UKR → ITA", duration: "08m 44s", size: "4.5 GB", path: "/media/Doc/Mariupol/Mariupol.it.srt" },
];

const SAMPLE_LOG = [
  { t: "14:02:11", lvl: "info",    msg: "🎉 Transcriber Pro avviato" },
  { t: "14:02:11", lvl: "info",    msg: "🎨 TMDB Client: ✅ Attivo" },
  { t: "14:02:11", lvl: "info",    msg: "⚙️ Profilo attivo: Bilanciato" },
  { t: "14:02:14", lvl: "info",    msg: "➕ Aggiunti 6 file alla coda" },
  { t: "14:03:02", lvl: "info",    msg: "🎬 Avvio: The Northman (2022).mkv" },
  { t: "14:03:04", lvl: "muted",   msg: "Warm-up: [████████░░] 80%" },
  { t: "14:03:18", lvl: "muted",   msg: "Demucs: [██████░░░░] 60% — separazione voce" },
  { t: "14:04:02", lvl: "muted",   msg: "Trascrizione: [█████████░] 92%" },
  { t: "14:04:31", lvl: "muted",   msg: "Traduzione: [██████░░░░] 67%" },
  { t: "14:04:31", lvl: "info",    msg: "Progresso: 67% — ETA 4m 22s" },
  { t: "14:04:32", lvl: "success", msg: "✅ Segmento 142/210 completato" },
];

const SUBTITLE_LANGUAGES = [
  ["Italiano","ita"],["Inglese","eng"],["Francese","fra"],["Spagnolo","spa"],
  ["Tedesco","deu"],["Portoghese","por"],["Russo","rus"],["Giapponese","jpn"],
  ["Cinese Sempl.","zho"],["Arabo","ara"],["Coreano","kor"],["Olandese","nld"],
  ["Polacco","pol"],["Turco","tur"],
];

const PROFILES = [
  { id: "veloce",      name: "Veloce",     desc: "Whisper Small · 2× più veloce" },
  { id: "bilanciato",  name: "Bilanciato", desc: "Whisper Medium · qualità/velocità ottimali" },
  { id: "qualita",     name: "Qualità",    desc: "Whisper Large-v3 · massima accuratezza" },
  { id: "ultra",       name: "Ultra",      desc: "Whisper Large-v3 + Demucs · post-processing" },
];

// ───────────────────────────────────────────────────────────
// SPLITTER
// ───────────────────────────────────────────────────────────
function Splitter({ orientation = "vertical", onDrag }) {
  const draggingRef = useRef(false);
  const onMouseDown = (e) => {
    draggingRef.current = true;
    document.body.style.cursor = orientation === "vertical" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  };
  useEffect(() => {
    const onMove = (e) => { if (draggingRef.current) onDrag(e); };
    const onUp = () => {
      if (draggingRef.current) {
        draggingRef.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [onDrag]);
  return (
    <div className={`splitter splitter-${orientation}`} onMouseDown={onMouseDown}
         role="separator" aria-orientation={orientation === "vertical" ? "vertical" : "horizontal"}>
      <div className="splitter-grip" />
    </div>
  );
}

// ───────────────────────────────────────────────────────────
// ATOMS
// ───────────────────────────────────────────────────────────
function MetricBar({ icon, label, value, suffix = "%", accent = "var(--accent)", detail }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="metric">
      <div className="metric-head">
        <span className="metric-icon" style={{ color: accent }}>{icon}</span>
        <span className="metric-label">{label}</span>
        <span className="metric-value mono">{value.toFixed(value < 10 ? 1 : 0)}{suffix}</span>
      </div>
      <div className="metric-track">
        <div className="metric-fill" style={{ width: `${pct}%`, background: accent }} />
      </div>
      {detail && <div className="metric-detail mono">{detail}</div>}
    </div>
  );
}

function FileRow({ file, selected, onClick }) {
  const statusMap = {
    processing: { dot: "var(--accent)",  label: "in corso" },
    queued:     { dot: "var(--muted)",   label: "in coda" },
    done:       { dot: "var(--success)", label: "completato" },
  };
  const s = statusMap[file.status];
  return (
    <button className={`file-row ${selected ? "is-selected" : ""}`} onClick={onClick}>
      <span className="file-status-dot" style={{ background: s.dot }} />
      <div className="file-info">
        <div className="file-name">{file.name}</div>
        <div className="file-meta mono">
          <span>{file.size}</span><span className="dot-sep">·</span>
          <span>{file.lang}</span><span className="dot-sep">·</span>
          <span style={{ color: s.dot }}>{s.label}</span>
        </div>
        {file.status === "processing" && (
          <div className="file-progress">
            <div className="file-progress-fill" style={{ width: `${file.progress}%` }} />
          </div>
        )}
      </div>
      <span className="file-grip"><Icon d={ICONS.grip} size={14}/></span>
    </button>
  );
}

function Toggle({ checked, onChange, compact }) {
  return (
    <button type="button" role="switch" aria-checked={checked}
            className={`toggle ${checked ? "is-on" : ""} ${compact ? "compact" : ""}`}
            onClick={(e) => { e.stopPropagation(); onChange(!checked); }}>
      <span className="toggle-thumb" />
    </button>
  );
}

function Segmented({ options, value, onChange }) {
  return (
    <div className="segmented" role="tablist">
      {options.map(o => (
        <button key={o.value} role="tab" aria-selected={value === o.value}
                className={`segmented-btn ${value === o.value ? "is-active" : ""}`}
                onClick={() => onChange(o.value)}>
          {o.label}
          {o.count != null && <span className="segmented-count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

// ───────────────────────────────────────────────────────────
// PROFILE POPOVER
// ───────────────────────────────────────────────────────────
function ProfilePopover({ profile, onSelect, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    const onClick = (e) => { if (!e.target.closest(".profile-popover, .profile-chip")) onClose(); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onClick); };
  }, [onClose]);
  return (
    <div className="profile-popover" role="menu">
      <div className="popover-head">Profilo di trascrizione</div>
      <div className="popover-list">
        {PROFILES.map(p => (
          <button key={p.id} className={`popover-item ${profile === p.id ? "is-active" : ""}`}
                  onClick={() => { onSelect(p.id); onClose(); }}>
            <div className="popover-item-radio">
              {profile === p.id && <Icon d={ICONS.check} size={12} stroke={2.5}/>}
            </div>
            <div className="popover-item-text">
              <div className="popover-item-name">{p.name}</div>
              <div className="popover-item-desc">{p.desc}</div>
            </div>
          </button>
        ))}
      </div>
      <div className="popover-foot">
        <span>Applicato a tutti i nuovi job</span>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────
// SETTINGS DIALOG (tabbed)
// ───────────────────────────────────────────────────────────
const SETTINGS_TABS = [
  { id: "general",      label: "Generali",      icon: ICONS.wrench },
  { id: "transcription",label: "Trascrizione",  icon: ICONS.mic },
  { id: "translation",  label: "Traduzione",    icon: ICONS.globe },
  { id: "batch",        label: "Batch adattivo",icon: ICONS.target },
  { id: "opensubs",     label: "OpenSubtitles", icon: ICONS.cloud },
];

function SettingsDialog({ open, onClose }) {
  const [tab, setTab] = useState("general");
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    if (open) document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <header className="dialog-head">
          <h2>Impostazioni</h2>
          <button className="icon-btn ghost" onClick={onClose} aria-label="Chiudi"><Icon d={ICONS.x} size={16}/></button>
        </header>
        <div className="dialog-body">
          <nav className="dialog-nav">
            {SETTINGS_TABS.map(t => (
              <button key={t.id} className={`dialog-nav-item ${tab === t.id ? "is-active" : ""}`} onClick={() => setTab(t.id)}>
                <Icon d={t.icon} size={15}/>
                <span>{t.label}</span>
              </button>
            ))}
          </nav>
          <div className="dialog-content">
            <SettingsContent tab={tab}/>
          </div>
        </div>
      </div>
    </div>
  );
}

function FieldRow({ label, hint, children }) {
  return (
    <div className="field-row">
      <div className="field-label">
        <div className="field-label-text">{label}</div>
        {hint && <div className="field-hint">{hint}</div>}
      </div>
      <div className="field-control">{children}</div>
    </div>
  );
}

function SettingsContent({ tab }) {
  if (tab === "general") return (
    <>
      <h3 className="content-title">Cartelle e comportamento</h3>
      <FieldRow label="Cartella di output predefinita" hint="Dove vengono salvati i sottotitoli generati">
        <div className="path-input">
          <input className="text-input" defaultValue="/media/Film & Serie TV"/>
          <button className="btn btn-secondary btn-sm"><Icon d={ICONS.folder} size={13}/> Sfoglia</button>
        </div>
      </FieldRow>
      <FieldRow label="Lingua interfaccia"><select className="text-input"><option>Italiano</option><option>English</option></select></FieldRow>
      <FieldRow label="TMDB lookup poster" hint="Scarica i poster dei film via The Movie DB">
        <Toggle checked={true} onChange={()=>{}}/>
      </FieldRow>
      <FieldRow label="Verbosità log" hint="Quanto dettaglio vedere nel pannello log">
        <select className="text-input"><option>Normale</option><option>Verbose</option><option>Debug</option></select>
      </FieldRow>
    </>
  );
  if (tab === "transcription") return (
    <>
      <h3 className="content-title">Modello di trascrizione</h3>
      <p className="content-desc">Il profilo qualità (in alto a destra) seleziona automaticamente uno di questi modelli. Qui puoi mettere a punto i parametri avanzati.</p>
      <FieldRow label="Device" hint="Dispositivo di calcolo per Whisper">
        <select className="text-input"><option>CUDA · NVIDIA RTX 4090</option><option>CPU</option></select>
      </FieldRow>
      <FieldRow label="Beam size" hint="Più alto = più accurato, più lento"><input className="text-input" type="number" defaultValue={5}/></FieldRow>
      <FieldRow label="VAD (Voice Activity Detection)" hint="Salta i silenzi"><Toggle checked={true} onChange={()=>{}}/></FieldRow>
      <FieldRow label="Compute type"><select className="text-input"><option>float16</option><option>int8</option><option>float32</option></select></FieldRow>
    </>
  );
  if (tab === "translation") return (
    <>
      <h3 className="content-title">Modello di traduzione</h3>
      <FieldRow label="Modello"><select className="text-input"><option>NLLB-200 distilled 600M</option><option>NLLB-200 1.3B</option><option>NLLB-200 3.3B (consigliato)</option></select></FieldRow>
      <FieldRow label="Device"><select className="text-input"><option>CUDA</option><option>CPU</option></select></FieldRow>
      <FieldRow label="Batch size"><input className="text-input" type="number" defaultValue={8}/></FieldRow>
    </>
  );
  if (tab === "batch") return (
    <>
      <h3 className="content-title">Batch adattivo</h3>
      <p className="content-desc">Adatta dinamicamente la dimensione dei batch in base alla VRAM disponibile.</p>
      <FieldRow label="Abilita batch adattivo"><Toggle checked={true} onChange={()=>{}}/></FieldRow>
      <FieldRow label="VRAM massima utilizzabile" hint="Margine di sicurezza per altri processi"><input className="text-input" type="number" defaultValue={85}/></FieldRow>
      <FieldRow label="Batch size minimo"><input className="text-input" type="number" defaultValue={1}/></FieldRow>
      <FieldRow label="Batch size massimo"><input className="text-input" type="number" defaultValue={32}/></FieldRow>
    </>
  );
  if (tab === "opensubs") return (
    <>
      <h3 className="content-title">Account OpenSubtitles</h3>
      <FieldRow label="Username"><input className="text-input" defaultValue="user@example.com"/></FieldRow>
      <FieldRow label="Password"><input className="text-input" type="password" defaultValue="••••••••"/></FieldRow>
      <FieldRow label="API key"><input className="text-input" type="password" defaultValue="sk_••••••••"/></FieldRow>
      <FieldRow label="Upload automatico" hint="Anche disponibile come toggle nella schermata principale"><Toggle checked={true} onChange={()=>{}}/></FieldRow>
    </>
  );
  return null;
}

// ───────────────────────────────────────────────────────────
// MAIN APP
// ───────────────────────────────────────────────────────────
function App() {
  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "theme": "dark",
    "accent": "cyan",
    "density": "comfortable"
  }/*EDITMODE-END*/;
  const useTweaksHook = window.useTweaks || ((d) => [d, () => {}]);
  const [tweaks, setTweak] = useTweaksHook(TWEAK_DEFAULTS);

  // Layout
  const [leftWidth, setLeftWidth]   = useState(380);
  const [rightWidth, setRightWidth] = useState(420);
  const [topHeight, setTopHeight]   = useState(58);
  const containerRef = useRef(null);

  // Tabs (top-level)
  const [topTab, setTopTab] = useState("queue");

  // App state
  const [files, setFiles] = useState(SAMPLE_FILES);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [filter, setFilter] = useState("all");
  const [isProcessing, setIsProcessing] = useState(true);
  const [shutdownAfter, setShutdownAfter] = useState(false);
  const [uploadOS, setUploadOS] = useState(true);
  const [genderCorrection, setGenderCorrection] = useState(false);
  const [targetLang, setTargetLang] = useState("ita");
  const [profile, setProfile] = useState("bilanciato");
  const [profileOpen, setProfileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [jobOpen, setJobOpen] = useState(false);
  const [historySearch, setHistorySearch] = useState("");

  const [metrics, setMetrics] = useState({ cpu: 42, ram: 58, gpu: 78, vram: 6.2, vramPct: 52, dn: 2.4, up: 0.3 });
  useEffect(() => {
    if (!isProcessing) return;
    const id = setInterval(() => {
      setMetrics(m => ({
        cpu: Math.max(8, Math.min(98,  m.cpu  + (Math.random() - 0.5) * 18)),
        ram: Math.max(20, Math.min(94, m.ram  + (Math.random() - 0.5) * 6)),
        gpu: Math.max(15, Math.min(99, m.gpu  + (Math.random() - 0.5) * 22)),
        vram: Math.max(2, Math.min(11.5, m.vram + (Math.random() - 0.5) * 0.4)),
        vramPct: Math.max(15, Math.min(98, m.vramPct + (Math.random() - 0.5) * 5)),
        dn:  Math.max(0,  Math.min(12,   m.dn   + (Math.random() - 0.5) * 1.2)),
        up:  Math.max(0,  Math.min(2,    m.up   + (Math.random() - 0.5) * 0.3)),
      }));
    }, 1000);
    return () => clearInterval(id);
  }, [isProcessing]);

  useEffect(() => {
    if (!isProcessing) return;
    const id = setInterval(() => {
      setFiles(prev => prev.map(f => f.status === "processing"
        ? { ...f, progress: Math.min(100, f.progress + 0.3) }
        : f));
    }, 500);
    return () => clearInterval(id);
  }, [isProcessing]);

  const onLeftDrag = useCallback((e) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const w = e.clientX - rect.left - 16;
    setLeftWidth(Math.max(320, Math.min(rect.width - rightWidth - 360, w)));
  }, [rightWidth]);
  const onRightDrag = useCallback((e) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const w = rect.right - e.clientX - 16;
    setRightWidth(Math.max(320, Math.min(rect.width - leftWidth - 360, w)));
  }, [leftWidth]);
  const onTopDrag = useCallback((e) => {
    const center = document.getElementById("center-col");
    if (!center) return;
    const rect = center.getBoundingClientRect();
    const pct = ((e.clientY - rect.top) / rect.height) * 100;
    setTopHeight(Math.max(25, Math.min(85, pct)));
  }, []);

  const filteredFiles = useMemo(() => {
    if (filter === "all") return files;
    return files.filter(f => f.status === filter);
  }, [files, filter]);

  const counts = useMemo(() => ({
    all: files.length,
    queued: files.filter(f => f.status === "queued").length,
    processing: files.filter(f => f.status === "processing").length,
    done: files.filter(f => f.status === "done").length,
  }), [files]);

  const filteredHistory = useMemo(() => {
    if (!historySearch.trim()) return SAMPLE_HISTORY;
    const q = historySearch.toLowerCase();
    return SAMPLE_HISTORY.filter(h => h.name.toLowerCase().includes(q) || h.lang.toLowerCase().includes(q));
  }, [historySearch]);

  const selected = filteredFiles[selectedIdx] || filteredFiles[0];
  const overallProgress = useMemo(() => {
    if (files.length === 0) return 0;
    return files.reduce((acc, f) => acc + f.progress, 0) / files.length;
  }, [files]);

  const eta = "4m 22s";
  const accentMap = {
    cyan: "oklch(0.74 0.13 220)", violet: "oklch(0.7 0.16 295)",
    emerald: "oklch(0.72 0.15 160)", amber: "oklch(0.78 0.14 75)", coral: "oklch(0.7 0.17 25)",
  };
  const rootStyle = {
    "--accent": accentMap[tweaks.accent] || accentMap.cyan,
    "--density": tweaks.density === "compact" ? "0.85" : "1",
  };
  const profileLabel = PROFILES.find(p => p.id === profile)?.name || "Bilanciato";

  return (
    <div className={`app theme-${tweaks.theme} density-${tweaks.density}`} style={rootStyle}>
      {/* TITLE BAR */}
      <header className="titlebar">
        <div className="titlebar-left">
          <div className="brand">
            <div className="brand-mark">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="3" width="6" height="11" rx="3"/>
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8"/>
              </svg>
            </div>
            <div className="brand-text">
              <div className="brand-name">Transcriber<span className="brand-pro"> Pro</span></div>
              <div className="brand-sub">Trascrizione &amp; sottotitoli AI</div>
            </div>
          </div>
        </div>
        <div className="titlebar-center">
          <div className="status-pill">
            <span className={`status-dot ${isProcessing ? "is-live" : ""}`} />
            <span className="status-text">
              {isProcessing
                ? <>In elaborazione · <span className="mono">{counts.processing + counts.queued}</span> rimanenti · ETA <span className="mono">{eta}</span></>
                : <>In standby</>}
            </span>
          </div>
        </div>
        <div className="titlebar-right">
          <div className="profile-anchor">
            <button className="profile-chip" onClick={() => setProfileOpen(o => !o)}>
              <Icon d={ICONS.sparkle} size={14}/>
              <span>Profilo</span>
              <strong>{profileLabel}</strong>
              <Icon d={ICONS.chevDown} size={14}/>
            </button>
            {profileOpen && <ProfilePopover profile={profile} onSelect={setProfile} onClose={() => setProfileOpen(false)}/>}
          </div>
          <button className="icon-btn ghost" title="Impostazioni" onClick={() => setSettingsOpen(true)}>
            <Icon d={ICONS.settings}/>
          </button>
        </div>
      </header>

      {/* TOP TABS */}
      <nav className="top-tabs" role="tablist">
        <button role="tab" aria-selected={topTab === "queue"}
                className={`top-tab ${topTab === "queue" ? "is-active" : ""}`}
                onClick={() => setTopTab("queue")}>
          <Icon d={ICONS.list} size={14}/> Coda di processamento
          {counts.processing + counts.queued > 0 && (
            <span className="top-tab-badge">{counts.processing + counts.queued}</span>
          )}
        </button>
        <button role="tab" aria-selected={topTab === "history"}
                className={`top-tab ${topTab === "history" ? "is-active" : ""}`}
                onClick={() => setTopTab("history")}>
          <Icon d={ICONS.history} size={14}/> Cronologia
          <span className="top-tab-badge subtle">{SAMPLE_HISTORY.length}</span>
        </button>
      </nav>

      {/* MAIN */}
      {topTab === "queue" ? (
        <main className="main" ref={containerRef}>
          {/* LEFT: queue + job card + scanner */}
          <section className="panel left-panel" style={{ width: leftWidth }}>
            <div className="panel-header">
              <Segmented
                value={filter} onChange={setFilter}
                options={[
                  { value: "all",        label: "Tutti",      count: counts.all },
                  { value: "processing", label: "Attivi",     count: counts.processing },
                  { value: "queued",     label: "In coda",    count: counts.queued },
                  { value: "done",       label: "Completati", count: counts.done },
                ]}
              />
            </div>

            <div className="file-list" tabIndex={0}>
              {filteredFiles.map((f, i) => (
                <FileRow key={f.name} file={f} selected={selected && f.name === selected.name}
                         onClick={() => setSelectedIdx(i)} />
              ))}
              {filteredFiles.length === 0 && (
                <div className="empty-state">
                  <div className="empty-glyph"><Icon d={ICONS.film} size={40} stroke={1.2}/></div>
                  <div className="empty-title">Nessun file</div>
                  <div className="empty-hint">Trascina i video qui o usa i pulsanti qui sotto</div>
                </div>
              )}
            </div>

            <div className="panel-footer">
              <div className="action-row">
                <button className="btn btn-secondary"><Icon d={ICONS.plus} size={14}/> Aggiungi</button>
                <button className="btn btn-secondary"><Icon d={ICONS.folder} size={14}/> Cartella</button>
                <button className="btn btn-ghost btn-icon-only" title="Svuota coda"><Icon d={ICONS.trash} size={14}/></button>
              </div>

              {/* JOB CARD: opzioni per-job collassabili */}
              <div className={`job-card ${jobOpen ? "is-open" : ""}`}>
                <button className="job-card-head" onClick={() => setJobOpen(o => !o)}>
                  <span className="job-card-title">Opzioni job</span>
                  <span className="job-card-summary mono">
                    {targetLang.toUpperCase()}
                    {uploadOS && <> · <span style={{color:"var(--accent)"}}>↗ OS</span></>}
                    {genderCorrection && <> · ⚧</>}
                    {shutdownAfter && <> · ⏻</>}
                  </span>
                  <Icon d={jobOpen ? ICONS.chevDown : ICONS.chevRight} size={14} style={{color:"var(--fg-2)"}}/>
                </button>
                {jobOpen && (
                  <div className="job-card-body">
                    <div className="job-row">
                      <div className="job-row-text">
                        <Icon d={ICONS.language} size={14}/>
                        <span>Lingua sottotitoli</span>
                      </div>
                      <div className="select-wrap">
                        <select value={targetLang} onChange={e => setTargetLang(e.target.value)} className="select">
                          {SUBTITLE_LANGUAGES.map(([n, c]) => <option key={c} value={c}>{n}</option>)}
                        </select>
                        <Icon d={ICONS.chevDown} size={14}/>
                      </div>
                    </div>
                    <div className="job-divider"/>
                    <label className="job-row clickable" onClick={() => setUploadOS(v => !v)}>
                      <div className="job-row-text">
                        <Icon d={ICONS.cloud} size={14}/>
                        <span>Upload su OpenSubtitles</span>
                      </div>
                      <div className="job-row-tail">
                        <button className="micro-btn" onClick={(e) => { e.stopPropagation(); setSettingsOpen(true); }} title="Configura">
                          <Icon d={ICONS.settings} size={12}/>
                        </button>
                        <Toggle compact checked={uploadOS} onChange={setUploadOS}/>
                      </div>
                    </label>
                    <div className="job-divider"/>
                    <label className="job-row clickable" onClick={() => setGenderCorrection(v => !v)}>
                      <div className="job-row-text">
                        <Icon d={ICONS.female} size={14}/>
                        <span>Correzione di genere</span>
                      </div>
                      <Toggle compact checked={genderCorrection} onChange={setGenderCorrection}/>
                    </label>
                    <div className="job-divider"/>
                    <label className="job-row clickable" onClick={() => setShutdownAfter(v => !v)}>
                      <div className="job-row-text">
                        <Icon d={ICONS.power} size={14}/>
                        <span>Spegni il PC al termine</span>
                      </div>
                      <Toggle compact checked={shutdownAfter} onChange={setShutdownAfter}/>
                    </label>
                  </div>
                )}
              </div>

              {/* LIBRARY SCANNER — collassabile */}
              <button className={`scanner-card ${scannerOpen ? "is-open" : ""}`} onClick={() => setScannerOpen(o => !o)}>
                <div className="scanner-head">
                  <Icon d={ICONS.search} size={14}/>
                  <span className="scanner-title">Library Scanner</span>
                  <span className="scanner-status">Inattivo</span>
                  <Icon d={scannerOpen ? ICONS.chevDown : ICONS.chevRight} size={14} style={{marginLeft:"auto", color:"var(--fg-2)"}}/>
                </div>
                {scannerOpen && (
                  <div className="scanner-body" onClick={e => e.stopPropagation()}>
                    <div className="scanner-path mono">/media/Film &amp; Serie TV</div>
                    <div className="scanner-stats">
                      <div className="scanner-stat"><span className="mono">412</span><span>video</span></div>
                      <div className="scanner-stat"><span className="mono">38</span><span>senza .srt</span></div>
                      <div className="scanner-stat"><span className="mono">12 GB</span><span>liberi</span></div>
                    </div>
                    <div className="scanner-actions">
                      <button className="btn btn-secondary btn-sm"><Icon d={ICONS.folder} size={12}/> Cambia cartella</button>
                      <button className="btn btn-primary btn-sm"><Icon d={ICONS.search} size={12}/> Scansiona</button>
                    </div>
                  </div>
                )}
              </button>

              <div className="control-row">
                {!isProcessing ? (
                  <button className="btn btn-primary btn-lg" onClick={() => setIsProcessing(true)}>
                    <Icon d={ICONS.play} size={16}/> Avvia
                  </button>
                ) : (
                  <button className="btn btn-stop btn-lg" onClick={() => setIsProcessing(false)}>
                    <Icon d={ICONS.stop} size={16}/> Interrompi
                  </button>
                )}
              </div>

              <div className="overall-progress">
                <div className="op-head">
                  <span>Progresso totale</span>
                  <span className="mono">{overallProgress.toFixed(1)}%</span>
                </div>
                <div className="op-track">
                  <div className="op-fill" style={{ width: `${overallProgress}%` }} />
                </div>
              </div>
            </div>
          </section>

          <Splitter orientation="vertical" onDrag={onLeftDrag}/>

          {/* CENTER */}
          <section id="center-col" className="panel center-panel">
            <div className="preview-section" style={{ height: `${topHeight}%` }}>
              <div className="preview-header">
                <div className="preview-title">
                  <Icon d={ICONS.film} size={16}/>
                  <h2>Anteprima</h2>
                </div>
                {selected && (
                  <div className="preview-meta">
                    <span className="preview-filename">{selected.name}</span>
                  </div>
                )}
              </div>
              <div className="preview-stage">
                {selected ? (
                  <div className="poster-frame">
                    <div className="poster-art">
                      <div className="poster-stripes"/>
                      <div className="poster-label mono">[ poster · {selected.name.split(' (')[0]} ]</div>
                    </div>
                    <div className="poster-overlay">
                      <div className="poster-info">
                        <div className="poster-tag mono">{selected.lang}</div>
                        <div className="poster-title">{selected.name.replace(/\.[^.]+$/, "")}</div>
                        <div className="poster-stats mono">
                          <span>{selected.size}</span><span>·</span>
                          <span>{selected.status === "processing" ? `${selected.progress.toFixed(0)}%` :
                                 selected.status === "done" ? "Completato" : "In coda"}</span>
                        </div>
                      </div>
                      {selected.status === "processing" && (
                        <div className="poster-progress">
                          <div className="poster-progress-fill" style={{ width: `${selected.progress}%` }}/>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="empty-poster">
                    <Icon d={ICONS.film} size={48} stroke={1.2}/>
                    <div>Seleziona un file per vedere l'anteprima</div>
                  </div>
                )}
              </div>
            </div>

            <Splitter orientation="horizontal" onDrag={onTopDrag}/>

            <div className="monitor-section" style={{ height: `${100 - topHeight}%` }}>
              <div className="monitor-header">
                <div className="monitor-title">
                  <Icon d={ICONS.cpu} size={16}/>
                  <h2>Monitor risorse</h2>
                </div>
                <div className="monitor-uptime mono">UPTIME 02:47:18</div>
              </div>
              <div className="metrics-grid">
                <MetricBar icon={<Icon d={ICONS.cpu} size={14}/>}      label="CPU"  value={metrics.cpu}  accent="oklch(0.72 0.13 220)" detail="AMD Ryzen 9 7950X · 16C/32T"/>
                <MetricBar icon={<Icon d={ICONS.chip} size={14}/>}     label="RAM"  value={metrics.ram}  accent="oklch(0.74 0.14 150)" detail="DDR5 · 64 GB"/>
                <MetricBar icon={<Icon d={ICONS.gpu} size={14}/>}      label="GPU"  value={metrics.gpu}  accent="oklch(0.7 0.16 295)"  detail="NVIDIA RTX 4090"/>
                <MetricBar icon={<Icon d={ICONS.hardDrive} size={14}/>}label="VRAM" value={metrics.vramPct} suffix="%" accent="oklch(0.78 0.14 75)"
                           detail={`${metrics.vram.toFixed(1)} / 24.0 GB`}/>
              </div>
              <div className="net-grid">
                <div className="net-card">
                  <div className="net-icon" style={{color:"oklch(0.72 0.13 220)"}}><Icon d={ICONS.arrowDown} size={14}/></div>
                  <div className="net-meta">
                    <div className="net-label">Download</div>
                    <div className="net-value mono">{metrics.dn.toFixed(2)} MB/s</div>
                  </div>
                </div>
                <div className="net-card">
                  <div className="net-icon" style={{color:"oklch(0.78 0.14 75)"}}><Icon d={ICONS.arrowUp} size={14}/></div>
                  <div className="net-meta">
                    <div className="net-label">Upload</div>
                    <div className="net-value mono">{metrics.up.toFixed(2)} MB/s</div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <Splitter orientation="vertical" onDrag={onRightDrag}/>

          {/* RIGHT: log */}
          <section className="panel right-panel" style={{ width: rightWidth }}>
            <div className="panel-header">
              <div className="panel-title-row">
                <h2 className="panel-title"><Icon d={ICONS.caption} size={16}/> Log di processamento</h2>
              </div>
              <div className="log-stats">
                <div className="log-stat"><span className="log-stat-num mono">{counts.done}</span><span className="log-stat-label">Completati</span></div>
                <div className="log-stat"><span className="log-stat-num mono" style={{color:"var(--accent)"}}>{counts.processing}</span><span className="log-stat-label">In corso</span></div>
                <div className="log-stat"><span className="log-stat-num mono">{counts.queued}</span><span className="log-stat-label">In coda</span></div>
                <div className="log-stat"><span className="log-stat-num mono">{eta}</span><span className="log-stat-label">ETA</span></div>
              </div>
            </div>
            <div className="log-window">
              {SAMPLE_LOG.map((l, i) => (
                <div key={i} className={`log-line lvl-${l.lvl}`}>
                  <span className="log-time mono">{l.t}</span>
                  <span className="log-msg">{l.msg}</span>
                </div>
              ))}
              <div className="log-line lvl-info live">
                <span className="log-time mono">14:04:32</span>
                <span className="log-msg"><span className="cursor-blink">▌</span> in attesa…</span>
              </div>
            </div>
            <div className="panel-footer right-footer">
              <div className="diagnostic-grid">
                <div className="diag"><Icon d={ICONS.clock} size={13}/><div><div className="diag-label">Tempo trascorso</div><div className="diag-value mono">02:47:18</div></div></div>
                <div className="diag"><Icon d={ICONS.mic} size={13}/><div><div className="diag-label">Modello</div><div className="diag-value">Whisper Large-v3</div></div></div>
                <div className="diag"><Icon d={ICONS.globe} size={13}/><div><div className="diag-label">Traduttore</div><div className="diag-value">NLLB-200 3.3B</div></div></div>
                <div className="diag"><Icon d={ICONS.alert} size={13}/><div><div className="diag-label">Errori</div><div className="diag-value mono">0</div></div></div>
              </div>
            </div>
          </section>
        </main>
      ) : (
        // ─── HISTORY TAB ───
        <main className="main history-main">
          <section className="panel history-panel">
            <div className="panel-header history-header">
              <div className="history-head-row">
                <h2 className="panel-title"><Icon d={ICONS.history} size={16}/> Cronologia</h2>
                <div className="history-search">
                  <Icon d={ICONS.search} size={14}/>
                  <input type="text" placeholder="Cerca per nome o lingua…"
                         value={historySearch} onChange={(e) => setHistorySearch(e.target.value)}/>
                </div>
              </div>
              <div className="history-stats">
                <div className="hist-stat"><span className="mono">{SAMPLE_HISTORY.length}</span><span>file processati</span></div>
                <div className="hist-stat"><span className="mono">42 GB</span><span>video totali</span></div>
                <div className="hist-stat"><span className="mono">1h 28m</span><span>tempo CPU</span></div>
              </div>
            </div>
            <div className="history-list">
              <div className="history-list-head">
                <span>Nome file</span>
                <span>Data</span>
                <span>Lingua</span>
                <span>Durata</span>
                <span>Dimensione</span>
                <span></span>
              </div>
              {filteredHistory.map((h, i) => (
                <div key={i} className="history-row">
                  <div className="history-cell history-name">
                    <Icon d={ICONS.caption} size={14}/>
                    <div>
                      <div className="history-filename">{h.name.replace(/\.[^.]+$/, "")}</div>
                      <div className="history-path mono">{h.path}</div>
                    </div>
                  </div>
                  <div className="history-cell">{h.date}</div>
                  <div className="history-cell"><span className="lang-pill mono">{h.lang}</span></div>
                  <div className="history-cell mono">{h.duration}</div>
                  <div className="history-cell mono">{h.size}</div>
                  <div className="history-cell history-actions">
                    <button className="btn btn-ghost btn-sm" title="Apri sottotitolo"><Icon d={ICONS.caption} size={13}/> Apri .srt</button>
                    <button className="btn btn-ghost btn-sm" title="Apri cartella"><Icon d={ICONS.folder} size={13}/> Cartella</button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </main>
      )}

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)}/>

      <TweaksUI tweaks={tweaks} setTweak={setTweak} />
    </div>
  );
}

function TweaksUI({ tweaks, setTweak }) {
  if (!window.TweaksPanel) return null;
  const { TweaksPanel, TweakSection, TweakRadio, TweakSelect } = window;
  return (
    <TweaksPanel title="Tweaks">
      <TweakSection title="Aspetto">
        <TweakRadio label="Tema" value={tweaks.theme} onChange={v => setTweak("theme", v)}
                    options={[{value:"dark",label:"Scuro"},{value:"light",label:"Chiaro"}]}/>
        <TweakSelect label="Accent" value={tweaks.accent} onChange={v => setTweak("accent", v)}
                     options={[
                       {value:"cyan",   label:"Ciano elettrico"},
                       {value:"violet", label:"Viola"},
                       {value:"emerald",label:"Smeraldo"},
                       {value:"amber",  label:"Ambra"},
                       {value:"coral",  label:"Corallo"},
                     ]}/>
        <TweakRadio label="Densità" value={tweaks.density} onChange={v => setTweak("density", v)}
                    options={[{value:"comfortable",label:"Comoda"},{value:"compact",label:"Compatta"}]}/>
      </TweakSection>
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
