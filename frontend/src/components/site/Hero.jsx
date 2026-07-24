import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { ArrowUpRight, Github, Globe, Play } from "lucide-react";
import { Mist } from "../Mist";
import { TranslateWidget } from "./TranslateWidget";

const line = {
  hidden: { y: "110%" },
  visible: (i) => ({
    y: "0%",
    transition: { duration: 0.9, delay: 0.25 + i * 0.12, ease: [0.22, 1, 0.36, 1] },
  }),
};

const MaskLine = ({ children, i }) => (
  <span className="block overflow-hidden pb-[0.12em]">
    <motion.span variants={line} custom={i} initial="hidden" animate="visible" className="block">
      {children}
    </motion.span>
  </span>
);

export const Hero = () => {
  return (
    <section
      id="top"
      className="relative flex min-h-screen items-center overflow-hidden pt-32 pb-16"
      data-testid="hero-section"
    >
      <Mist />
      <div className="grain absolute inset-0 opacity-60" aria-hidden="true" />

      <div className="relative z-10 mx-auto w-full max-w-7xl px-5 sm:px-6">

        <h1 className="font-display text-[13vw] font-black leading-[0.92] tracking-tighter text-slate-900 sm:text-[10vw] lg:text-[8.2rem]">
          <MaskLine i={0}>Break every</MaskLine>
          <MaskLine i={1}>
            <span className="text-[#0a52ff]">language</span>{" "}
            <span className="font-serif-editorial font-normal italic tracking-normal text-slate-500">
              barrier,
            </span>
          </MaskLine>
          <MaskLine i={2}>live.</MaskLine>
        </h1>

        <div className="mt-10 grid gap-12 lg:grid-cols-[1fr_0.92fr] lg:items-start">
          <div>
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 0.7 }}
              className="max-w-xl text-lg leading-relaxed text-slate-600"
              data-testid="hero-subtitle"
            >
              SUSI Translator delivers real-time AI transcription, translation and
              text-to-speech for any live event, conference or virtual show across{" "}
              <span className="font-semibold text-slate-900">200+ languages</span> and{" "}
              <span className="font-semibold text-slate-900">35+ voices</span>. Plug it into
              HLS, Vimeo, Twitch and beyond.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 0.85 }}
              className="mt-8 flex flex-wrap items-center gap-3"
            >
              <motion.div whileTap={{ scale: 0.96 }}>
                <Link
                  to="/demo"
                  className="group inline-flex items-center gap-2 rounded-full bg-[#0a52ff] px-7 py-4 text-base font-semibold text-white shadow-[0_12px_34px_rgba(10,82,255,0.35)] transition-shadow hover:shadow-[0_16px_44px_rgba(10,82,255,0.5)]"
                  data-testid="hero-cta-primary"
                >
                  <Play className="h-4 w-4 fill-current" /> Open the playground
                </Link>
              </motion.div>
              <motion.a
                whileTap={{ scale: 0.96 }}
                href="#opensource"
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/70 px-7 py-4 text-base font-semibold text-slate-800 backdrop-blur transition-all hover:border-slate-300 hover:shadow-sm"
                data-testid="hero-cta-secondary"
              >
                <Github className="h-4 w-4" /> See it open source <ArrowUpRight className="h-4 w-4" />
              </motion.a>
            </motion.div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 1, delay: 1.1 }}
              className="mt-10 flex flex-wrap items-center gap-x-8 gap-y-3 text-sm text-slate-500"
              data-testid="hero-trust"
            >
              <span className="flex items-center gap-2">
                <Globe className="h-4 w-4 text-[#0a52ff]" /> Connecting people in their native language
              </span>
              <span className="hidden h-4 w-px bg-slate-200 sm:block" />
              <span>Speech-to-text · Translation · Text-to-speech</span>
            </motion.div>
          </div>

          <TranslateWidget />
        </div>
      </div>
    </section>
  );
};
