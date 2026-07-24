import { useEffect, useRef, useState } from "react";
import { motion, useInView } from "framer-motion";
import { Reveal } from "../Reveal";

const Counter = ({ to, suffix = "" }) => {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (!inView) return;
    let raf;
    const start = performance.now();
    const dur = 1400;
    const tick = (now) => {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(Math.round(eased * to));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, to]);
  return (
    <span ref={ref}>
      {val}
      {suffix}
    </span>
  );
};

const stats = [
  { to: 200, suffix: "+", label: "Languages for speech-to-text" },
  { to: 35, suffix: "+", label: "Natural text-to-speech voices" },
  { to: 300, suffix: "ms", label: "Typical end-to-end latency" },
  { to: 100, suffix: "%", label: "Open source, self-hostable" },
];

export const Stats = () => (
  <section id="stats" className="relative overflow-hidden py-28" data-testid="stats-section">
    <div className="absolute inset-0 -z-10">
      <motion.div
        className="absolute left-1/4 top-1/2 h-[30rem] w-[30rem] -translate-y-1/2 rounded-full bg-blue-400/20 blur-[130px]"
        animate={{ x: [0, 80, 0] }}
        transition={{ duration: 20, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
    <div className="mx-auto max-w-7xl px-5 sm:px-6">
      <div className="grid grid-cols-2 gap-y-14 lg:grid-cols-4">
        {stats.map((s, i) => (
          <Reveal key={s.label} delay={i * 0.08} className="text-center">
            <div className="font-display text-6xl font-black tracking-tighter text-[#0a52ff] sm:text-7xl">
              <Counter to={s.to} suffix={s.suffix} />
            </div>
            <p className="mx-auto mt-3 max-w-[12rem] text-sm leading-relaxed text-slate-600">
              {s.label}
            </p>
          </Reveal>
        ))}
      </div>
    </div>
  </section>
);
