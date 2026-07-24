import { motion } from "framer-motion";
import { Radio, Video, Twitch, Rss, Globe, Cast } from "lucide-react";
import { Reveal } from "../Reveal";

const sources = [
  { icon: Radio, name: "HLS streams" },
  { icon: Video, name: "Vimeo" },
  { icon: Twitch, name: "Twitch" },
  { icon: Cast, name: "RTMP" },
  { icon: Rss, name: "Custom feeds" },
  { icon: Globe, name: "Web embeds" },
];

export const Sources = () => (
  <section className="relative py-24" data-testid="sources-section">
    <div className="mx-auto max-w-7xl px-5 sm:px-6">
      <Reveal className="mb-12 text-center">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-slate-400">
          Plug into any live source
        </p>
      </Reveal>
      <div className="relative flex overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_15%,black_85%,transparent)]">
        <div className="flex w-max animate-marquee items-center gap-4 py-4 hover:[animation-play-state:paused]">
          {[...sources, ...sources, ...sources, ...sources].map((s, i) => (
            <div
              key={`${s.name}-${i}`}
              className="flex w-44 flex-col items-center gap-3 rounded-2xl border border-slate-100 bg-white/70 px-4 py-8 backdrop-blur transition-shadow hover:shadow-[0_12px_30px_rgba(10,82,255,0.08)]"
              data-testid={`source-${s.name.toLowerCase().replace(/\s/g, "-")}`}
            >
              <s.icon className="h-7 w-7 text-[#0a52ff]" strokeWidth={1.8} />
              <span className="text-sm font-semibold text-slate-700 whitespace-nowrap">{s.name}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  </section>
);
