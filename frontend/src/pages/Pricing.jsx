import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { Check, Github, Cloud, Building2, ArrowRight } from "lucide-react";
import { Mist } from "../components/Mist";
import { Reveal } from "../components/Reveal";

const tiers = [
  {
    icon: Github,
    name: "Open Source",
    price: "Free",
    sub: "self-hosted",
    desc: "The full SUSI Translator stack. Run it anywhere, forever.",
    features: [
      "200+ languages · speech-to-text",
      "35+ text-to-speech voices",
      "faster-whisper · NLLB-200 · Supertonic",
      "Mic, file & stream inputs",
      "MIT license, no limits",
    ],
    cta: "Get the code",
    to: "/docs",
    highlight: false,
  },
  {
    icon: Cloud,
    name: "Cloud",
    price: "$0",
    sub: "then usage-based",
    desc: "Managed SUSI with autoscaling GPUs. Skip the ops, start in seconds.",
    features: [
      "Everything in Open Source",
      "Hosted real-time pipeline",
      "Live captions for HLS · Vimeo · Twitch",
      "Team workspace & API keys",
      "Priority community support",
    ],
    cta: "Start free",
    to: "/demo",
    highlight: true,
  },
  {
    icon: Building2,
    name: "Enterprise",
    price: "Custom",
    sub: "let's talk",
    desc: "For platforms embedding SUSI at scale with compliance needs.",
    features: [
      "Everything in Cloud",
      "Dedicated / on-prem deployment",
      "SSO, audit logs & SLAs",
      "Custom model fine-tuning",
      "Solution engineering",
    ],
    cta: "Contact sales",
    to: "/demo",
    highlight: false,
  },
];

export default function Pricing() {
  return (
    <div className="relative overflow-hidden pt-32" data-testid="pricing-page">
      <Mist className="opacity-60" />
      <div className="relative z-10 mx-auto max-w-7xl px-5 pb-28 sm:px-6">
        <Reveal className="mx-auto max-w-2xl text-center">
          <span className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-4 py-1.5 text-sm font-semibold text-[#0a52ff]">
            Pricing
          </span>
          <h1 className="mt-6 font-display text-5xl font-black tracking-tighter text-slate-900 sm:text-6xl">
            Open by default.
          </h1>
          <p className="mt-5 text-lg leading-relaxed text-slate-600">
            Self-host the entire platform for free, or let us run it for you.
            No paywalls on the core, ever.
          </p>
        </Reveal>

        <div className="mt-16 grid gap-6 lg:grid-cols-3">
          {tiers.map((t, i) => (
            <Reveal key={t.name} delay={i * 0.1}>
              <motion.div
                whileHover={{ y: -6 }}
                transition={{ type: "spring", stiffness: 300, damping: 22 }}
                className={`relative flex h-full flex-col rounded-[2rem] p-8 ${
                  t.highlight
                    ? "bg-slate-900 text-white shadow-[0_24px_60px_rgba(10,82,255,0.25)]"
                    : "border border-slate-100 bg-white text-slate-900"
                }`}
                data-testid={`pricing-tier-${t.name.toLowerCase().replace(/\s/g, "-")}`}
              >
                {t.highlight && (
                  <span className="absolute right-6 top-6 rounded-full bg-[#0a52ff] px-3 py-1 text-xs font-semibold text-white">
                    Most popular
                  </span>
                )}
                <div
                  className={`mb-6 flex h-12 w-12 items-center justify-center rounded-2xl ${
                    t.highlight ? "bg-white/10 text-blue-300" : "bg-blue-50 text-[#0a52ff]"
                  }`}
                >
                  <t.icon className="h-6 w-6" />
                </div>
                <h3 className="font-display text-2xl font-bold tracking-tight">{t.name}</h3>
                <div className="mt-4 flex items-end gap-2">
                  <span className="font-display text-5xl font-black tracking-tighter">
                    {t.price}
                  </span>
                  <span className={`mb-1.5 text-sm ${t.highlight ? "text-slate-400" : "text-slate-500"}`}>
                    {t.sub}
                  </span>
                </div>
                <p className={`mt-4 leading-relaxed ${t.highlight ? "text-slate-300" : "text-slate-600"}`}>
                  {t.desc}
                </p>
                <ul className="mt-7 flex flex-1 flex-col gap-3">
                  {t.features.map((f) => (
                    <li key={f} className="flex items-start gap-3 text-sm">
                      <Check
                        className={`mt-0.5 h-4 w-4 shrink-0 ${
                          t.highlight ? "text-blue-300" : "text-[#0a52ff]"
                        }`}
                      />
                      <span className={t.highlight ? "text-slate-200" : "text-slate-700"}>{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  to={t.to}
                  className={`mt-8 inline-flex items-center justify-center gap-2 rounded-full px-6 py-3.5 text-sm font-semibold transition-transform hover:scale-[1.02] ${
                    t.highlight
                      ? "bg-white text-slate-900"
                      : "bg-[#0a52ff] text-white"
                  }`}
                  data-testid={`pricing-cta-${t.name.toLowerCase().replace(/\s/g, "-")}`}
                >
                  {t.cta} <ArrowRight className="h-4 w-4" />
                </Link>
              </motion.div>
            </Reveal>
          ))}
        </div>
      </div>
    </div>
  );
}
