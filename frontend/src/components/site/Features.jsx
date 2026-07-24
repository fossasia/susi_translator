import { motion } from "framer-motion";
import { Mic, Languages, Volume2, Cpu, Radio, Github } from "lucide-react";
import { Reveal } from "../Reveal";

const features = [
  {
    icon: Mic,
    title: "Speech-to-text",
    desc: "Accurate real-time transcription across 200+ languages and dialects, tuned for live speaker audio.",
    tag: "200+ languages",
    span: "lg:col-span-2",
  },
  {
    icon: Languages,
    title: "Live translation",
    desc: "Translate captions on the fly with any AI model you plug in.",
    tag: "Any model",
  },
  {
    icon: Volume2,
    title: "Text-to-speech",
    desc: "Natural voices that carry tone across languages.",
    tag: "35+ voices",
  },
  {
    icon: Radio,
    title: "Any stream source",
    desc: "HLS direct streams, Vimeo, Twitch and more. Drop in a URL and go live.",
    tag: "HLS · Vimeo · Twitch",
    span: "lg:col-span-2",
  },
  {
    icon: Cpu,
    title: "Bring your own model",
    desc: "Model-agnostic pipeline. Swap providers without rewiring your stack.",
    tag: "Composable",
  },
  {
    icon: Github,
    title: "Truly open source",
    desc: "Self-host it, fork it, embed it into your own event platform. No lock-in, ever.",
    tag: "MIT spirit",
    span: "lg:col-span-2",
  },
];

export const Features = () => (
  <section className="relative py-28" data-testid="features-section">
    <div className="mx-auto max-w-7xl px-5 sm:px-6">
      <Reveal className="mb-16 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div className="max-w-2xl">
          <span className="text-sm font-semibold uppercase tracking-[0.2em] text-[#0a52ff]">
            Capabilities
          </span>
          <h2 className="mt-4 font-display text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
            One toolkit for borderless events.
          </h2>
        </div>
        <p className="max-w-sm text-lg leading-relaxed text-slate-600">
          Everything you need to make any broadcast understandable to anyone,
          anywhere. Built to be embedded and extended.
        </p>
      </Reveal>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-4">
        {features.map((f, i) => (
          <Reveal
            key={f.title}
            delay={(i % 3) * 0.08}
            className={f.span || "lg:col-span-2"}
          >
            <motion.div
              whileHover={{ y: -6 }}
              transition={{ type: "spring", stiffness: 300, damping: 22 }}
              className="group relative h-full overflow-hidden rounded-[1.75rem] border border-slate-100 bg-white p-8 transition-shadow hover:shadow-[0_20px_50px_rgba(10,82,255,0.08)]"
              data-testid={`feature-card-${i}`}
            >
              <div className="pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full bg-blue-400/10 blur-3xl transition-opacity group-hover:opacity-100" />
              <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-[#0a52ff]">
                <f.icon className="h-6 w-6" strokeWidth={2} />
              </div>
              <h3 className="font-display text-2xl font-bold tracking-tight text-slate-900">
                {f.title}
              </h3>
              <p className="mt-3 max-w-md leading-relaxed text-slate-600">{f.desc}</p>
              <span className="mt-6 inline-block rounded-full border border-blue-100 bg-blue-50/60 px-3 py-1 text-xs font-semibold text-[#0a52ff]">
                {f.tag}
              </span>
            </motion.div>
          </Reveal>
        ))}
      </div>
    </div>
  </section>
);
