import { motion } from "framer-motion";

// Ambient Sarvam-style mist: soft, drifting blurred blue/cyan orbs on white.
export const Mist = ({ className = "" }) => {
  const blobs = [
    {
      c: "bg-blue-400/30",
      size: "h-[38rem] w-[38rem]",
      pos: "top-[-10rem] left-[-8rem]",
      anim: { x: [0, 60, 0], y: [0, 40, 0] },
      dur: 18,
    },
    {
      c: "bg-cyan-300/30",
      size: "h-[32rem] w-[32rem]",
      pos: "top-[6rem] right-[-6rem]",
      anim: { x: [0, -50, 0], y: [0, 50, 0] },
      dur: 22,
    },
    {
      c: "bg-blue-600/20",
      size: "h-[30rem] w-[30rem]",
      pos: "bottom-[-8rem] left-[30%]",
      anim: { x: [0, 40, 0], y: [0, -40, 0] },
      dur: 26,
    },
  ];
  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
      data-testid="mist-layer"
    >
      {blobs.map((b, i) => (
        <motion.div
          key={i}
          className={`absolute rounded-full blur-[120px] ${b.c} ${b.size} ${b.pos}`}
          animate={b.anim}
          transition={{ duration: b.dur, repeat: Infinity, ease: "easeInOut" }}
        />
      ))}
    </div>
  );
};
