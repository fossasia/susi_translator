import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Link } from "react-router-dom";
import { Sparkles, ArrowRight, Loader2 } from "lucide-react";

const LANGS = [
  { code: "hi", name: "Hindi", country: "in" },
  { code: "es", name: "Spanish", country: "es" },
  { code: "ja", name: "Japanese", country: "jp" },
  { code: "ar", name: "Arabic", country: "sa", rtl: true },
  { code: "fr", name: "French", country: "fr" },
  { code: "zh", name: "Mandarin", country: "cn" },
];

const EXAMPLES = [
  {
    src: "Welcome everyone to the summit.",
    t: {
      hi: "शिखर सम्मेलन में सभी का स्वागत है।",
      es: "Bienvenidos todos a la cumbre.",
      ja: "サミットへようこそ、皆さん。",
      ar: "مرحبًا بالجميع في القمة.",
      fr: "Bienvenue à tous au sommet.",
      zh: "欢迎大家参加峰会。",
    },
  },
  {
    src: "Language should never be a barrier.",
    t: {
      hi: "भाषा कभी बाधा नहीं बननी चाहिए।",
      es: "El idioma nunca debería ser una barrera.",
      ja: "言語が壁になってはいけません。",
      ar: "يجب ألا تكون اللغة عائقًا أبدًا.",
      fr: "La langue ne devrait jamais être une barrière.",
      zh: "语言永远不应成为障碍。",
    },
  },
  {
    src: "Let's connect the world in real time.",
    t: {
      hi: "आइए दुनिया को वास्तविक समय में जोड़ें।",
      es: "Conectemos el mundo en tiempo real.",
      ja: "世界をリアルタイムでつなげましょう。",
      ar: "لنربط العالم في الوقت الفعلي.",
      fr: "Connectons le monde en temps réel.",
      zh: "让我们实时连接世界。",
    },
  },
];

const norm = (s) => s.toLowerCase().trim().replace(/\s+/g, " ");

export const TranslateWidget = () => {
  const [text, setText] = useState(EXAMPLES[0].src);
  const [translating, setTranslating] = useState(false);

  const match = useMemo(
    () => EXAMPLES.find((e) => norm(e.src) === norm(text)),
    [text]
  );
  const active = match || EXAMPLES[0];
  const isCustom = !match && text.trim().length > 0;

  useEffect(() => {
    setTranslating(true);
    const t = setTimeout(() => setTranslating(false), 550);
    return () => clearTimeout(t);
  }, [text]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, delay: 0.9, ease: [0.22, 1, 0.36, 1] }}
      className="glass w-full rounded-[1.75rem] p-5 sm:p-6"
      data-testid="translate-widget"
    >
      <div className="mb-4 flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <Sparkles className="h-4 w-4 text-[#0a52ff]" /> Try it live
        </span>
        <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-semibold text-[#0a52ff]">
          6 languages
        </span>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white/80 p-3">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type a sentence…"
          className="w-full bg-transparent text-base text-slate-900 outline-none placeholder:text-slate-400"
          data-testid="translate-widget-input"
          aria-label="Sentence to translate"
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2" data-testid="translate-widget-chips">
        {EXAMPLES.map((e, i) => (
          <button
            key={i}
            onClick={() => setText(e.src)}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              norm(e.src) === norm(text)
                ? "border-[#0a52ff] bg-[#0a52ff] text-white"
                : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
            }`}
            data-testid={`translate-widget-chip-${i}`}
          >
            {e.src.length > 26 ? e.src.slice(0, 26) + "…" : e.src}
          </button>
        ))}
      </div>

      <div className="mt-5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {LANGS.map((l, i) => (
          <div
            key={l.code}
            className="rounded-xl border border-slate-100 bg-white/70 p-3"
            data-testid={`translate-out-${l.code}`}
          >
            <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-slate-500">
              <img src={`https://flagcdn.com/w20/${l.country}.png`} alt={l.name} className="w-4 rounded-sm" /> {l.name}
            </div>
            <div className="min-h-[1.5rem]">
              <AnimatePresence mode="wait">
                {translating ? (
                  <motion.div
                    key="load"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="flex items-center gap-1.5 text-slate-300"
                  >
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span className="h-2 w-20 rounded-full bg-slate-100" />
                  </motion.div>
                ) : (
                  <motion.p
                    key={active.src + l.code}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, delay: i * 0.05 }}
                    dir={l.rtl ? "rtl" : "ltr"}
                    className="text-sm leading-snug text-slate-800"
                  >
                    {active.t[l.code]}
                  </motion.p>
                )}
              </AnimatePresence>
            </div>
          </div>
        ))}
      </div>

      {isCustom && (
        <div
          className="mt-4 flex items-center justify-between gap-3 rounded-xl bg-blue-50/70 px-4 py-3 text-sm"
          data-testid="translate-widget-custom-hint"
        >
          <span className="text-slate-600">
            Showing a sample phrase. Translate <b>any</b> sentence in the playground.
          </span>
          <Link
            to="/demo"
            className="inline-flex shrink-0 items-center gap-1 font-semibold text-[#0a52ff]"
          >
            Open <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}
    </motion.div>
  );
};
