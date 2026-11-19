/* Original flat illustrations, drawn inline so the page makes no image requests and works offline.
   Palette: navy #142b4a, blue #2563eb, teal #0f9d92 (see styles.css). Decorative: aria-hidden unless a title is given. */

export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <path d="M20 3 33 8v10c0 9-5.6 15.6-13 19C12.6 33.6 7 27 7 18V8z" fill="#2563eb" />
      <path d="M20 3 33 8v10c0 9-5.6 15.6-13 19z" fill="#0f9d92" />
      <path d="m14 20 4.5 4.5L27 15.5" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Student at a desk with a laptop, protected by a shield, with a phone, earbuds case, tablet and bicycle around them. */
export function HeroArt() {
  return (
    <svg className="hero-art" viewBox="0 0 520 440" role="img" aria-label="Illustration of a student at a laptop, with a phone, tablet, earbuds and bicycle protected by a shield">
      <rect x="20" y="30" width="480" height="380" rx="24" fill="#1d3a63" />
      <circle cx="400" cy="90" r="46" fill="#27497a" />
      {/* shield */}
      <path d="M260 40 380 84v96c0 82-50 142-120 172C190 322 140 262 140 180V84z" fill="#2563eb" />
      <path d="M260 40 380 84v96c0 82-50 142-120 172z" fill="#0f9d92" />
      <path d="m214 190 36 36 62-70" fill="none" stroke="#fff" strokeWidth="14" strokeLinecap="round" strokeLinejoin="round" />
      {/* desk */}
      <rect x="60" y="350" width="400" height="14" rx="4" fill="#0e2038" />
      <rect x="90" y="364" width="12" height="46" fill="#0e2038" /><rect x="418" y="364" width="12" height="46" fill="#0e2038" />
      {/* student */}
      <circle cx="140" cy="256" r="24" fill="#f2c9a5" />
      <path d="M116 252c2-22 20-30 36-24 10 4 14 14 12 24-10-8-26-12-48 0z" fill="#142b4a" />
      <path d="M100 350v-48c0-22 18-34 40-34s40 12 40 34v48z" fill="#f5b301" />
      <path d="M176 318l50 24" stroke="#f2c9a5" strokeWidth="14" strokeLinecap="round" />
      {/* laptop */}
      <path d="M210 262h110l12 88H198z" fill="#e8effd" />
      <rect x="220" y="272" width="90" height="62" rx="3" fill="#142b4a" />
      <path d="M232 322l22-26 16 16 14-18 18 28z" fill="#0f9d92" opacity=".9" />
      <rect x="186" y="346" width="160" height="8" rx="4" fill="#c4d2ea" />
      {/* phone */}
      <g transform="rotate(8 410 300)"><rect x="380" y="256" width="52" height="96" rx="9" fill="#e8effd" /><rect x="386" y="266" width="40" height="70" rx="4" fill="#142b4a" /><circle cx="406" cy="344" r="3" fill="#8aa0c4" /></g>
      {/* tablet */}
      <g transform="rotate(-6 80 150)"><rect x="42" y="110" width="84" height="108" rx="9" fill="#e8effd" /><rect x="50" y="120" width="68" height="86" rx="4" fill="#142b4a" /><rect x="58" y="132" width="40" height="6" rx="3" fill="#0f9d92" /><rect x="58" y="146" width="52" height="5" rx="2" fill="#5878a8" /><rect x="58" y="158" width="46" height="5" rx="2" fill="#5878a8" /></g>
      {/* earbuds case */}
      <g><rect x="414" y="190" width="58" height="40" rx="16" fill="#e8effd" /><path d="M414 208h58" stroke="#c4d2ea" strokeWidth="2" /><circle cx="443" cy="208" r="3" fill="#0f9d92" /></g>
      {/* bicycle */}
      <g fill="none" stroke="#7fa2d8" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="64" cy="388" r="18" /><circle cx="120" cy="388" r="18" /><path d="M64 388l22-34h30l-24 34M86 354l-6-12h-8M110 354h8" />
      </g>
    </svg>
  );
}

const S = { stroke: '#142b4a', strokeWidth: 3, strokeLinejoin: 'round' as const, strokeLinecap: 'round' as const };

const ART: Record<string, JSX.Element> = {
  Laptop: <><path d="M48 24h104a6 6 0 0 1 6 6v68H42V30a6 6 0 0 1 6-6z" fill="#142b4a" /><rect x="52" y="32" width="96" height="58" rx="2" fill="#2563eb" /><path d="M60 82l24-28 18 18 14-16 26 26z" fill="#0f9d92" /><path d="M24 104h152l-10 14a6 6 0 0 1-5 3H39a6 6 0 0 1-5-3z" fill="#c4d2ea" {...S} /></>,
  Smartphone: <><rect x="72" y="10" width="56" height="116" rx="11" fill="#142b4a" /><rect x="78" y="22" width="44" height="88" rx="3" fill="#2563eb" /><circle cx="100" cy="118" r="3.5" fill="#8aa0c4" /><rect x="92" y="14" width="16" height="3.5" rx="2" fill="#8aa0c4" /><path d="M82 100l16-22 10 12 8-9 6 19z" fill="#0f9d92" /></>,
  Tablet: <><rect x="46" y="14" width="108" height="112" rx="10" fill="#142b4a" /><rect x="54" y="22" width="92" height="96" rx="3" fill="#2563eb" /><rect x="64" y="34" width="52" height="8" rx="4" fill="#fff" opacity=".9" /><rect x="64" y="50" width="70" height="6" rx="3" fill="#bcd0f7" /><rect x="64" y="62" width="62" height="6" rx="3" fill="#bcd0f7" /><path d="M64 108l22-24 16 14 12-10 20 20z" fill="#0f9d92" /></>,
  Earbuds: <><rect x="46" y="58" width="108" height="64" rx="28" fill="#e8effd" {...S} /><path d="M46 84h108" stroke="#142b4a" strokeWidth="3" /><circle cx="100" cy="84" r="5" fill="#0f9d92" /><g fill="#2563eb" {...S}><path d="M72 58V30a10 10 0 0 1 20 0v28z" /><path d="M108 58V30a10 10 0 0 1 20 0v28z" /></g></>,
  Bicycle: <><g fill="none" stroke="#142b4a" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"><circle cx="48" cy="96" r="28" /><circle cx="152" cy="96" r="28" /><path d="M48 96l34-52h46l24 52M82 44l22 52h-56M70 36h24M128 44l-6-14h-14" stroke="#2563eb" /></g><circle cx="104" cy="96" r="6" fill="#0f9d92" /></>,
  Smartwatch: <><rect x="82" y="6" width="36" height="30" rx="6" fill="#c4d2ea" /><rect x="82" y="104" width="36" height="30" rx="6" fill="#c4d2ea" /><rect x="64" y="30" width="72" height="80" rx="18" fill="#142b4a" /><rect x="71" y="38" width="58" height="64" rx="12" fill="#2563eb" /><circle cx="100" cy="70" r="20" fill="none" stroke="#fff" strokeWidth="3" /><path d="M100 58v13l9 6" fill="none" stroke="#0f9d92" strokeWidth="4" strokeLinecap="round" /><rect x="136" y="56" width="6" height="14" rx="2" fill="#8aa0c4" /></>,
};

/** Illustration for an asset category by name; unknown (administrator-added) categories get a neutral shield. */
export function AssetArt({ kind }: { kind: string }) {
  return (
    <svg viewBox="0 0 200 140" aria-hidden="true" focusable="false">
      {ART[kind] ?? <path d="M100 14 150 32v40c0 30-20 52-50 62-30-10-50-32-50-62V32z" fill="#2563eb" />}
    </svg>
  );
}
