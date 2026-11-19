/* Original flat illustrations drawn for this project (no stock images, no external files, no gradients).
   Palette: navy #142B4A, blue #2563EB, teal #0F9D92, tints #E3EEFD / #D5F0ED. Presentation attributes only, so the strict CSP (no inline <style>) is fine. */
const NAVY = '#142B4A', BLUE = '#2563EB', BLUE_D = '#1E4FD0', TEAL = '#0F9D92', TINT = '#E3EEFD', TINT_T = '#D5F0ED', STEEL = '#9DB4D9', WHITE = '#FFFFFF';

export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="StudentBelongings Cover logo">
      <path d="M16 2.5 L27 6.5 V15 C27 21.6 22.4 26.8 16 29.5 C9.6 26.8 5 21.6 5 15 V6.5 Z" fill={NAVY} />
      <path d="M16 2.5 L27 6.5 V15 C27 21.6 22.4 26.8 16 29.5 Z" fill="#1B3A63" />
      <path d="M10.8 15.6 L14.6 19.4 L21.4 11.8" fill="none" stroke={TEAL} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function HeroArt() {
  return (
    <svg viewBox="0 0 560 440" role="img" aria-labelledby="hero-art-t" className="hero-art">
      <title id="hero-art-t">A student at a desk with a laptop, phone, smartwatch and earbuds, protected by a shield</title>
      <rect x="0" y="0" width="560" height="440" rx="28" fill={TINT} />
      <circle cx="455" cy="95" r="120" fill="#D2E2FB" />
      <circle cx="90" cy="360" r="95" fill={TINT_T} />
      {/* floating accents */}
      <circle cx="72" cy="86" r="7" fill={TEAL} /><circle cx="520" cy="250" r="6" fill={BLUE} /><circle cx="330" cy="40" r="5" fill={NAVY} />
      <path d="M470 292 h14 M477 285 v14" stroke={TEAL} strokeWidth="3" strokeLinecap="round" />
      <path d="M40 200 h12 M46 194 v12" stroke={BLUE} strokeWidth="3" strokeLinecap="round" />
      {/* student behind the laptop */}
      <path d="M170 176 C170 144 196 134 232 134 C268 134 294 144 294 176 Z" fill={TEAL} />
      <rect x="219" y="112" width="26" height="28" rx="8" fill="#E9B98F" />
      <circle cx="232" cy="96" r="30" fill="#F2C9A5" />
      <path d="M201 92 C199 66 218 58 234 58 C252 58 266 70 263 92 C255 84 246 78 232 78 C220 78 208 82 201 92 Z" fill="#33241C" />
      <circle cx="203" cy="102" r="5.5" fill={WHITE} /><circle cx="261" cy="102" r="5.5" fill={WHITE} />
      <circle cx="222" cy="99" r="2.6" fill={NAVY} /><circle cx="242" cy="99" r="2.6" fill={NAVY} />
      <path d="M224 111 Q232 117 240 111" fill="none" stroke="#9A5B3C" strokeWidth="2.4" strokeLinecap="round" />
      {/* laptop */}
      <rect x="108" y="170" width="248" height="152" rx="12" fill={NAVY} />
      <rect x="120" y="182" width="224" height="128" rx="5" fill={WHITE} />
      <path d="M232 196 L262 207 V232 C262 249 249 261 232 268 C215 261 202 249 202 232 V207 Z" fill={BLUE} />
      <path d="M232 196 L262 207 V232 C262 249 249 261 232 268 Z" fill={BLUE_D} />
      <path d="M217 233 L228 244 L248 221" fill="none" stroke={WHITE} strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="146" y="282" width="172" height="8" rx="4" fill={TINT} /><rect x="176" y="296" width="112" height="6" rx="3" fill={TINT} />
      <path d="M84 322 H380 L370 338 H94 Z" fill={STEEL} />
      <rect x="206" y="322" width="52" height="6" rx="3" fill="#7C97C4" />
      {/* desk */}
      <rect x="36" y="338" width="488" height="16" rx="8" fill={NAVY} />
      <rect x="70" y="354" width="12" height="62" fill="#1B3A63" /><rect x="478" y="354" width="12" height="62" fill="#1B3A63" />
      {/* phone */}
      <rect x="392" y="210" width="76" height="128" rx="14" fill={NAVY} />
      <rect x="398" y="220" width="64" height="108" rx="7" fill={WHITE} />
      <circle cx="430" cy="258" r="19" fill={TEAL} />
      <path d="M421 258 L428 265 L440 250" fill="none" stroke={WHITE} strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="410" y="288" width="40" height="6" rx="3" fill={TINT} /><rect x="416" y="300" width="28" height="6" rx="3" fill={TINT} />
      <rect x="418" y="213" width="24" height="4" rx="2" fill="#2B4670" />
      {/* smartwatch */}
      <rect x="52" y="262" width="26" height="76" rx="6" fill={TEAL} />
      <rect x="44" y="282" width="42" height="42" rx="13" fill={NAVY} />
      <rect x="49" y="287" width="32" height="32" rx="9" fill={WHITE} />
      <path d="M65 303 V294 M65 303 L72 307" stroke={NAVY} strokeWidth="3" strokeLinecap="round" />
      {/* earbuds + case */}
      <rect x="474" y="306" width="48" height="32" rx="15" fill={WHITE} stroke={NAVY} strokeWidth="3" />
      <path d="M474 320 H522" stroke={NAVY} strokeWidth="2" />
      <circle cx="498" cy="329" r="2.5" fill={TEAL} />
      <ellipse cx="432" cy="333" rx="6" ry="5" fill={WHITE} stroke={NAVY} strokeWidth="2" />
      {/* shield */}
      <path d="M418 40 L478 62 V108 C478 142 454 168 418 182 C382 168 358 142 358 108 V62 Z" fill={BLUE} />
      <path d="M418 40 L478 62 V108 C478 142 454 168 418 182 Z" fill={BLUE_D} />
      <path d="M390 108 L412 130 L448 86" fill="none" stroke={WHITE} strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" />
      {/* rupee coin */}
      <circle cx="318" cy="116" r="26" fill={TEAL} /><circle cx="318" cy="116" r="19" fill="none" stroke={WHITE} strokeWidth="2" opacity="0.7" />
      <text x="318" y="125" textAnchor="middle" fontSize="26" fontWeight="700" fill={WHITE} fontFamily="Inter Variable, system-ui, sans-serif">₹</text>
    </svg>
  );
}

const Disc = () => <circle cx="60" cy="45" r="40" fill={TINT} />;
const ART: Record<string, JSX.Element> = {
  Laptop: <><Disc /><rect x="30" y="22" width="60" height="40" rx="4" fill={NAVY} /><rect x="34" y="26" width="52" height="32" rx="2" fill={WHITE} />
    <path d="M60 30 L70 34 V43 C70 49 65 53 60 55 C55 53 50 49 50 43 V34 Z" fill={BLUE} /><path d="M55 43 L59 47 L66 38" fill="none" stroke={WHITE} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M18 66 H102 L97 73 H23 Z" fill={STEEL} /></>,
  Smartphone: <><Disc /><rect x="43" y="12" width="34" height="66" rx="8" fill={NAVY} /><rect x="47" y="19" width="26" height="52" rx="2.5" fill={WHITE} />
    <circle cx="60" cy="42" r="8" fill={TEAL} /><path d="M56 42 L59 45 L64 39" fill="none" stroke={WHITE} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    <rect x="52" y="56" width="16" height="3" rx="1.5" fill={TINT} /><rect x="55" y="62" width="10" height="3" rx="1.5" fill={TINT} /><circle cx="60" cy="15.5" r="1.4" fill="#2B4670" /></>,
  Tablet: <><Disc /><rect x="24" y="18" width="72" height="54" rx="7" fill={NAVY} /><rect x="30" y="24" width="60" height="42" rx="2.5" fill={WHITE} />
    <rect x="36" y="31" width="22" height="22" rx="4" fill={BLUE} /><rect x="64" y="31" width="20" height="5" rx="2.5" fill={TINT} /><rect x="64" y="41" width="14" height="5" rx="2.5" fill={TINT} /><rect x="64" y="51" width="18" height="5" rx="2.5" fill={TINT} /><circle cx="93" cy="45" r="1.6" fill="#2B4670" /></>,
  Earbuds: <><Disc /><rect x="36" y="38" width="48" height="34" rx="16" fill={WHITE} stroke={NAVY} strokeWidth="3" /><path d="M36 53 H84" stroke={NAVY} strokeWidth="2" /><circle cx="60" cy="63" r="2.6" fill={TEAL} />
    <circle cx="44" cy="26" r="8" fill={WHITE} stroke={NAVY} strokeWidth="3" /><rect x="41.5" y="30" width="5" height="12" rx="2.5" fill={WHITE} stroke={NAVY} strokeWidth="2.5" />
    <circle cx="76" cy="26" r="8" fill={WHITE} stroke={NAVY} strokeWidth="3" /><rect x="73.5" y="30" width="5" height="12" rx="2.5" fill={WHITE} stroke={NAVY} strokeWidth="2.5" /></>,
  Bicycle: <><Disc /><circle cx="33" cy="58" r="16" fill="none" stroke={NAVY} strokeWidth="4" /><circle cx="87" cy="58" r="16" fill="none" stroke={NAVY} strokeWidth="4" />
    <path d="M33 58 L52 58 L44 36 H76 L52 58 M76 36 L87 58" fill="none" stroke={TEAL} strokeWidth="4" strokeLinejoin="round" strokeLinecap="round" />
    <path d="M76 36 L73 28 H82 M39 36 L48 30 H38" fill="none" stroke={NAVY} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" /><circle cx="33" cy="58" r="3" fill={NAVY} /><circle cx="87" cy="58" r="3" fill={NAVY} /></>,
  Smartwatch: <><Disc /><rect x="48" y="8" width="24" height="26" rx="5" fill={TEAL} /><rect x="48" y="56" width="24" height="26" rx="5" fill={TEAL} />
    <rect x="38" y="26" width="44" height="40" rx="13" fill={NAVY} /><rect x="43" y="31" width="34" height="30" rx="9" fill={WHITE} />
    <path d="M60 46 V37 M60 46 L67 50" stroke={NAVY} strokeWidth="3" strokeLinecap="round" /><circle cx="60" cy="46" r="2.4" fill={BLUE} /></>,
};

export function CategoryArt({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 120 90" role="img" aria-label={`${name} illustration`} className="cat-art">
      {ART[name] ?? <><Disc /><rect x="40" y="25" width="40" height="40" rx="8" fill={NAVY} /></>}
    </svg>
  );
}
