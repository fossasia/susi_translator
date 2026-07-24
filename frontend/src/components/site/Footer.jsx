import { motion } from "framer-motion";
import { Languages, Github, ArrowUpRight } from "lucide-react";
import { Mist } from "../Mist";

const cols = [
  { title: "Product", links: ["Live translation", "Speech-to-text", "Text-to-speech", "Stream sources"] },
  { title: "Use cases", links: ["Conferences", "Virtual shows", "Online meetings", "Event platforms"] },
  { title: "Community", links: ["GitHub", "Docs", "Contributing", "Changelog"] },
];

export const Footer = () => (
  <footer className="relative overflow-hidden bg-slate-900 text-white" data-testid="footer">
    <div className="relative py-28">
      <Mist className="opacity-30" />
      <div className="relative z-10 mx-auto max-w-7xl px-5 sm:px-6">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8 }}
          className="max-w-4xl"
        >
          <h2 className="font-display text-5xl font-black leading-[0.95] tracking-tighter sm:text-7xl">
            Let the world{" "}
            <span className="font-serif-editorial font-normal italic text-blue-300">
              understand you.
            </span>
          </h2>
          <div className="mt-10 flex flex-wrap gap-4">
            <motion.a
              whileTap={{ scale: 0.96 }}
              href="#demo"
              className="inline-flex items-center gap-2 rounded-full bg-white px-7 py-4 text-base font-semibold text-slate-900 transition-transform hover:scale-[1.02]"
              data-testid="footer-cta-primary"
            >
              Get started free
            </motion.a>
            <motion.a
              whileTap={{ scale: 0.96 }}
              href="https://github.com/fossasia/susi_translator"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-full border border-white/25 px-7 py-4 text-base font-semibold text-white transition-colors hover:bg-white/10"
              data-testid="footer-cta-github"
            >
              <Github className="h-5 w-5" /> Star on GitHub <ArrowUpRight className="h-4 w-4" />
            </motion.a>
          </div>
        </motion.div>

        <div className="mt-24 grid gap-12 border-t border-white/10 pt-16 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#0a52ff] text-white">
                <Languages className="h-5 w-5" />
              </span>
              <span className="font-display text-lg font-extrabold tracking-tight">
                SUSI<span className="text-blue-400">.</span>Translator
              </span>
            </div>
            <p className="mt-5 max-w-xs leading-relaxed text-slate-400">
              Real-time AI transcription, translation and speech for a world
              without language barriers. Open source, forever.
            </p>
            <div className="mt-6 flex gap-3">
              {[Github].map((Icon, i) => (
                <a
                  key={i}
                  href={Icon === Github ? "https://github.com/fossasia/susi_translator" : "https://github.com"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex h-10 w-10 items-center justify-center rounded-full border border-white/15 text-slate-300 transition-colors hover:border-white/40 hover:text-white"
                  aria-label="social link"
                >
                  <Icon className="h-4 w-4" />
                </a>
              ))}
            </div>
          </div>
          {cols.map((c) => (
            <div key={c.title}>
              <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                {c.title}
              </h4>
              <ul className="mt-5 space-y-3">
                {c.links.map((l) => (
                  <li key={l}>
                    <a href="#top" className="text-slate-300 transition-colors hover:text-white">
                      {l}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-16 flex flex-col items-start justify-between gap-4 border-t border-white/10 pt-8 text-sm text-slate-500 sm:flex-row sm:items-center">
          <span>© {new Date().getFullYear()} SUSI Translator. Open Source software by FOSSASIA.</span>
          <span>Connecting every region in its native language.</span>
        </div>
      </div>
    </div>
  </footer>
);
