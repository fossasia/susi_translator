import { motion } from "framer-motion";
import { Github, Star, GitFork, Terminal, ArrowUpRight } from "lucide-react";
import { Reveal } from "../Reveal";
import { Mist } from "../Mist";

export const OpenSource = () => (
  <section id="opensource" className="relative overflow-hidden py-28" data-testid="opensource-section">
    <Mist className="opacity-70" />
    <div className="relative z-10 mx-auto max-w-7xl px-5 sm:px-6">
      <div className="glass overflow-hidden rounded-[2.5rem] p-8 sm:p-14">
        <div className="grid gap-12 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
          <Reveal>
            <span className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-4 py-1.5 text-sm font-semibold text-[#0a52ff]">
              <Github className="h-4 w-4" /> Open source
            </span>
            <h2 className="mt-6 font-display text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
              Yours to run, fork and extend.
            </h2>
            <p className="mt-5 max-w-lg text-lg leading-relaxed text-slate-600">
              SUSI Translator ships with a fully open codebase. Embed it into your
              event management platform, self-host the pipeline, and swap in whichever
              AI models you trust. Community-built, community-owned.
            </p>

            <div className="mt-8 flex flex-wrap gap-8">
              {[
                { icon: Star, val: "1.0k", label: "Stars" },
                { icon: GitFork, val: "27", label: "Forks" },
                { icon: Terminal, val: "Apache 2.0", label: "License" },
              ].map((s) => (
                <div key={s.label} className="flex items-center gap-3">
                  <s.icon className="h-5 w-5 text-[#0a52ff]" />
                  <div>
                    <div className="font-display text-xl font-extrabold text-slate-900">{s.val}</div>
                    <div className="text-xs uppercase tracking-wide text-slate-400">{s.label}</div>
                  </div>
                </div>
              ))}
            </div>

            <motion.a
              whileTap={{ scale: 0.96 }}
              href="https://github.com/fossasia/susi_translator"
              target="_blank"
              rel="noopener noreferrer"
              className="mt-9 inline-flex items-center gap-2 rounded-full bg-[#0a52ff] px-7 py-4 text-base font-semibold text-white shadow-[0_12px_34px_rgba(10,82,255,0.35)] transition-shadow hover:shadow-[0_16px_44px_rgba(10,82,255,0.5)]"
              data-testid="opensource-github-btn"
            >
              <Github className="h-5 w-5" /> Explore the repo <ArrowUpRight className="h-4 w-4" />
            </motion.a>
          </Reveal>

          <Reveal delay={0.1}>
            <div className="overflow-hidden rounded-2xl border border-slate-800 bg-[#0b1020] shadow-2xl">
              <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
                <span className="h-3 w-3 rounded-full bg-red-400" />
                <span className="h-3 w-3 rounded-full bg-yellow-400" />
                <span className="h-3 w-3 rounded-full bg-green-400" />
                <span className="ml-3 text-xs font-medium text-slate-400">quickstart.sh</span>
              </div>
              <pre className="overflow-x-auto p-5 text-sm leading-relaxed">
                <code>
                  <span className="text-slate-500"># Clone & run SUSI Translator</span>{"\n"}
                  <span className="text-blue-400">git</span>{" "}
                  <span className="text-slate-200">clone https://github.com/fossasia/susi_translator.git</span>{"\n"}
                  <span className="text-blue-400">cd</span>{" "}
                  <span className="text-slate-200">susi_translator</span>{"\n\n"}
                  <span className="text-slate-500"># Sync dependencies & start backend</span>{"\n"}
                  <span className="text-blue-400">uv</span>{" "}
                  <span className="text-slate-200">sync</span>{"\n"}
                  <span className="text-blue-400">uv</span>{" "}
                  <span className="text-slate-200">run python flask/transcribe_server.py</span>{"\n\n"}
                  <span className="text-slate-500"># Grab any stream & start translating</span>{"\n"}
                  <span className="text-blue-400">uv</span>{" "}
                  <span className="text-slate-200">run python flask/audio_grabber.py url --url https://event.m3u8</span>
                </code>
              </pre>
            </div>
          </Reveal>
        </div>
      </div>
    </div>
  </section>
);
