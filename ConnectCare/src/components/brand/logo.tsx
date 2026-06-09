/**
 * ConnectCare wordmark — "Connect" (navy) over "Care" (brand green),
 * with the dotted-ring mark from the brand book.
 */
export function ConnectCareLogo({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <DottedRing className="h-9 w-9 shrink-0" />
      <div className="leading-[0.95]">
        <span className="block text-[15px] font-semibold tracking-tight text-navy">
          Connect
        </span>
        <span className="block text-[15px] font-semibold tracking-tight text-brand-500">
          Care
        </span>
      </div>
    </div>
  );
}

function DottedRing({ className = "" }: { className?: string }) {
  // 12 dots around a ring, fading from navy to brand green.
  const dots = Array.from({ length: 12 });
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden>
      {dots.map((_, i) => {
        const a = (i / dots.length) * Math.PI * 2 - Math.PI / 2;
        const cx = 20 + Math.cos(a) * 15;
        const cy = 20 + Math.sin(a) * 15;
        const t = i / dots.length;
        const r = 2.6 - t * 1.1;
        const color = t < 0.5 ? "#0a0a28" : "#008870";
        return <circle key={i} cx={cx} cy={cy} r={r} fill={color} opacity={0.85 - t * 0.3} />;
      })}
    </svg>
  );
}
