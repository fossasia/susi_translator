import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import {
  Terminal,
  Mic,
  FileAudio,
  Link2,
  Languages,
  Volume2,
  Cpu,
  BookOpen,
  ArrowRight,
} from "lucide-react";
import { Mist } from "../components/Mist";
import { Reveal } from "../components/Reveal";

const nav = [
  { label: "Quickstart", id: "quickstart" },
  { label: "Input sources", id: "inputs" },
  { label: "Models", id: "models" },
  { label: "Pipeline API", id: "api" },
];

const models = [
  {
    icon: Mic,
    kind: "Transcription",
    name: "faster-whisper",
    desc: "High-throughput speech-to-text across 200+ languages with word-level timing.",
  },
  {
    icon: Languages,
    kind: "Translation",
    name: "NLLB-200",
    desc: "No Language Left Behind, direct translation between 200 languages.",
  },
  {
    icon: Volume2,
    kind: "Text-to-speech",
    name: "Supertonic",
    desc: "Natural, low-latency neural voices for real-time playback.",
  },
];

const inputs = [
  { icon: Mic, title: "Browser microphone", desc: "Capture live audio straight from the browser, no install." },
  { icon: FileAudio, title: "Audio upload", desc: "Drop local .mp3, .wav and other audio files to process." },
  { icon: Link2, title: "Video / stream link", desc: "Point at an HLS .m3u8, Vimeo or Twitch URL." },
];

export default function Docs() {
  return (
    <div className="relative overflow-hidden pt-32" data-testid="docs-page">
      <Mist className="opacity-60" />
      <div className="relative z-10 mx-auto max-w-7xl px-5 pb-28 sm:px-6">
        <Reveal>
          <span className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-4 py-1.5 text-sm font-semibold text-[#0a52ff]">
            <BookOpen className="h-4 w-4" /> Documentation
          </span>
          <h1 className="mt-6 font-display text-5xl font-black tracking-tighter text-slate-900 sm:text-6xl">
            Build with SUSI Translator.
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-slate-600">
            Everything you need to run real-time transcription, translation and
            speech in your own event platform. Open source, self-hostable, model-agnostic.
          </p>
        </Reveal>

        <div className="mt-16 grid gap-12 lg:grid-cols-[220px_1fr]">
          <aside className="hidden lg:block">
            <div className="sticky top-28 flex flex-col gap-1">
              {nav.map((n) => (
                <a
                  key={n.id}
                  href={`#${n.id}`}
                  className="rounded-xl px-4 py-2.5 text-sm font-medium text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900"
                  data-testid={`docs-nav-${n.id}`}
                >
                  {n.label}
                </a>
              ))}
            </div>
          </aside>

          <div className="flex flex-col gap-20">
            <section id="quickstart" className="scroll-mt-28">
              <Reveal>
                <h2 className="font-display text-3xl font-bold tracking-tight text-slate-900">
                  Quickstart
                </h2>
                <p className="mt-3 max-w-2xl leading-relaxed text-slate-600">
                  Clone the repository, install dependencies, and point SUSI at any
                  live source. You will be translating in minutes.
                </p>
                <div className="mt-6 overflow-hidden rounded-2xl border border-slate-800 bg-[#0b1020]">
                  <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
                    <Terminal className="h-4 w-4 text-slate-400" />
                    <span className="text-xs font-medium text-slate-400">terminal</span>
                  </div>
                  <pre className="overflow-x-auto p-5 text-sm leading-relaxed">
                    <code>
                      <span className="text-slate-500"># Start by grabbing the source</span>{"\n"}
                      <span className="text-blue-400">git</span>{" "}
                      <span className="text-slate-200">clone https://github.com/fossasia/susi_translator.git</span>{"\n"}
                      <span className="text-blue-400">cd</span>{" "}
                      <span className="text-slate-200">susi_translator &amp;&amp; pip install -r requirements.txt</span>{"\n\n"}
                      <span className="text-slate-500"># Start the pipeline</span>{"\n"}
                      <span className="text-blue-400">python</span>{" "}
                      <span className="text-slate-200">-m susi.serve</span>{"\n"}
                      <span className="text-emerald-300">✓ listening on :8080</span>
                    </code>
                  </pre>
                </div>
              </Reveal>
            </section>

            <section id="inputs" className="scroll-mt-28">
              <Reveal>
                <h2 className="font-display text-3xl font-bold tracking-tight text-slate-900">
                  Input sources
                </h2>
                <p className="mt-3 max-w-2xl leading-relaxed text-slate-600">
                  SUSI accepts three kinds of input. Mic and file inputs run entirely
                  from the browser; links stream server-side.
                </p>
                <div className="mt-6 grid gap-4 sm:grid-cols-3">
                  {inputs.map((it) => (
                    <div
                      key={it.title}
                      className="rounded-2xl border border-slate-100 bg-white p-6"
                      data-testid={`docs-input-${it.title.toLowerCase().replace(/\s/g, "-")}`}
                    >
                      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-[#0a52ff]">
                        <it.icon className="h-5 w-5" />
                      </div>
                      <h3 className="font-semibold text-slate-900">{it.title}</h3>
                      <p className="mt-2 text-sm leading-relaxed text-slate-600">{it.desc}</p>
                    </div>
                  ))}
                </div>
              </Reveal>
            </section>

            <section id="models" className="scroll-mt-28">
              <Reveal>
                <h2 className="font-display text-3xl font-bold tracking-tight text-slate-900">
                  Models
                </h2>
                <p className="mt-3 max-w-2xl leading-relaxed text-slate-600">
                  Swap any stage of the pipeline. These are the defaults shipped with SUSI.
                </p>
                <div className="mt-6 flex flex-col gap-4">
                  {models.map((m) => (
                    <div
                      key={m.name}
                      className="flex flex-col gap-4 rounded-2xl border border-slate-100 bg-white p-6 sm:flex-row sm:items-center"
                      data-testid={`docs-model-${m.name}`}
                    >
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-[#0a52ff]">
                        <m.icon className="h-5 w-5" />
                      </div>
                      <div className="flex-1">
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                          {m.kind}
                        </span>
                        <h3 className="font-display text-xl font-bold text-slate-900">{m.name}</h3>
                        <p className="mt-1 text-sm leading-relaxed text-slate-600">{m.desc}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </Reveal>
            </section>

            <section id="api" className="scroll-mt-28">
              <Reveal>
                <h2 className="font-display text-3xl font-bold tracking-tight text-slate-900">
                  Pipeline API
                </h2>
                <p className="mt-3 max-w-2xl leading-relaxed text-slate-600">
                  A single streaming endpoint drives transcription, optional translation and
                  optional speech synthesis. Enable each stage per request.
                </p>
                <div className="mt-6 overflow-hidden rounded-2xl border border-slate-800 bg-[#0b1020]">
                  <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
                    <Cpu className="h-4 w-4 text-slate-400" />
                    <span className="text-xs font-medium text-slate-400">POST /api/stream</span>
                  </div>
                  <pre className="overflow-x-auto p-5 text-sm leading-relaxed text-slate-200">
{`{
  "input": { "type": "mic | file | link", "url": "…" },
  "source_language": "auto",
  "transcription_model": "faster-whisper",
  "translate": true,
  "translation_model": "NLLB-200",
  "targets": ["hi", "es", "ja", "ar", "fr", "zh"],
  "tts": true,
  "tts_model": "Supertonic"
}`}
                  </pre>
                </div>
                <div className="mt-8 flex flex-wrap gap-3">
                  <Link
                    to="/demo"
                    className="inline-flex items-center gap-2 rounded-full bg-[#0a52ff] px-6 py-3.5 text-sm font-semibold text-white"
                    data-testid="docs-cta-playground"
                  >
                    Open the playground <ArrowRight className="h-4 w-4" />
                  </Link>
                  <Link
                    to="/pricing"
                    className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-6 py-3.5 text-sm font-semibold text-slate-800 hover:border-slate-300"
                  >
                    See pricing
                  </Link>
                </div>
              </Reveal>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
