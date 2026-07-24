import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Radio, Volume2, Waves } from "lucide-react";
import { Reveal } from "../Reveal";

const stream = [
  { lang: "English", flag: "🇬🇧", src: "Original audio", text: "Welcome everyone to the global summit stage." },
  { lang: "हिन्दी", flag: "🇮🇳", src: "Translated", text: "वैश्विक शिखर मंच पर आप सभी का स्वागत है।" },
  { lang: "Español", flag: "🇪🇸", src: "Translated", text: "Bienvenidos todos al escenario de la cumbre global." },
  { lang: "日本語", flag: "🇯🇵", src: "Translated", text: "グローバルサミットのステージへようこそ。" },
  { lang: "العربية", flag: "🇸🇦", src: "Translated", text: "مرحبًا بالجميع على منصة القمة العالمية." },
];

export const LiveDemo = () => {
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setIdx((v) => (v + 1) % stream.length), 2600);
    return () => clearInterval(t);
  }, []);

  return (
    <section id="demo" className="relative py-28" data-testid="livedemo-section">
      <div className="mx-auto max-w-7xl px-5 sm:px-6">
        <Reveal className="mb-16 max-w-2xl">
          <span className="text-sm font-semibold uppercase tracking-[0.2em] text-[#0a52ff]">
            Live pipeline
          </span>
          <h2 className="mt-4 font-display text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
            Hear one voice. <span className="text-stroke-blue">Reach every room.</span>
          </h2>
          <p className="mt-5 text-lg leading-relaxed text-slate-600">
            Audio streams in, captions appear instantly, and translated speech
            flows back out, all in real time, powered by the AI model you choose.
          </p>
        </Reveal>

        <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <Reveal className="relative overflow-hidden rounded-[2rem] border border-slate-100">
            <img
              src="https://images.unsplash.com/photo-1540575467063-178a50c2df87?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"
              alt="Live conference stage"
              className="h-full min-h-[22rem] w-full object-cover"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-[#0a2a80]/70 via-transparent to-transparent" />
            <div className="absolute left-5 top-5 flex items-center gap-2 rounded-full bg-white/90 px-3 py-1.5 text-xs font-semibold text-slate-800 backdrop-blur">
              <Radio className="h-3.5 w-3.5 text-red-500" /> LIVE · Global Summit
            </div>
            <div className="absolute bottom-5 left-5 right-5 glass rounded-2xl p-4">
              <div className="mb-2 flex items-center gap-2 text-xs font-medium text-[#0a52ff]">
                <Mic className="h-3.5 w-3.5" /> Speaker input · English
              </div>
              <div className="flex items-end gap-1">
                {[...Array(28)].map((_, i) => (
                  <motion.span
                    key={i}
                    className="w-1.5 rounded-full bg-[#0a52ff]"
                    animate={{ height: [6, 8 + ((i * 7) % 26), 6] }}
                    transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.05 }}
                  />
                ))}
              </div>
            </div>
          </Reveal>

          <Reveal delay={0.1} className="flex flex-col gap-4">
            <div className="glass flex items-center justify-between rounded-2xl px-6 py-4">
              <div className="flex items-center gap-3">
                <Waves className="h-5 w-5 text-[#0a52ff]" />
                <span className="font-semibold text-slate-900">Live translation feed</span>
              </div>
              <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-[#0a52ff]">
                ~300ms latency
              </span>
            </div>

            <div className="relative min-h-[16rem] overflow-hidden rounded-2xl border border-slate-100 bg-white p-2">
              <AnimatePresence mode="popLayout">
                {[0, 1, 2].map((offset) => {
                  const item = stream[(idx + offset) % stream.length];
                  return (
                    <motion.div
                      key={`${item.lang}-${idx}-${offset}`}
                      layout
                      initial={{ opacity: 0, y: 24 }}
                      animate={{ opacity: offset === 0 ? 1 : 0.5 - offset * 0.12, y: 0 }}
                      exit={{ opacity: 0, y: -16 }}
                      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                      className={`m-2 rounded-xl border p-4 ${
                        offset === 0 ? "border-blue-100 bg-blue-50/50" : "border-slate-100 bg-white"
                      }`}
                    >
                      <div className="mb-1.5 flex items-center justify-between">
                        <span className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                          <span className="text-lg">{item.flag}</span> {item.lang}
                        </span>
                        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
                          {item.src}
                        </span>
                      </div>
                      <p className="text-base leading-snug text-slate-700">{item.text}</p>
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </div>

            <div className="glass flex items-center justify-between rounded-2xl px-6 py-4">
              <div className="flex items-center gap-3">
                <Volume2 className="h-5 w-5 text-[#0a52ff]" />
                <span className="font-semibold text-slate-900">Text-to-speech output</span>
              </div>
              <span className="text-sm text-slate-500">Aria · Kai · Mira · +32</span>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
};
