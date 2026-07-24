import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Languages,
  Mic,
  Square,
  Upload,
  Link2,
  Volume2,
  Play,
  Loader2,
  ArrowLeft,
  Lock,
  Sparkles,
  Waves,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "@/components/ui/sonner";

const SOURCE_LANGS = [
  { code: "auto", label: "Auto-detect" },
  { code: "en", label: "English" },
  { code: "hi", label: "Hindi" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "ar", label: "Arabic" },
  { code: "ja", label: "Japanese" },
  { code: "zh", label: "Mandarin Chinese" },
];

const TARGETS = [
  { code: "hi", name: "Hindi", country: "in", rtl: false },
  { code: "es", name: "Spanish", country: "es" },
  { code: "ja", name: "Japanese", country: "jp" },
  { code: "ar", name: "Arabic", country: "sa", rtl: true },
  { code: "fr", name: "French", country: "fr" },
  { code: "zh", name: "Mandarin", country: "cn" },
];

const SEGMENTS = [
  {
    en: "Welcome everyone to the global summit.",
    t: { hi: "वैश्विक शिखर सम्मेलन में सभी का स्वागत है।", es: "Bienvenidos todos a la cumbre global.", ja: "グローバルサミットへようこそ。", ar: "مرحبًا بالجميع في القمة العالمية.", fr: "Bienvenue à tous au sommet mondial.", zh: "欢迎大家参加全球峰会。" },
  },
  {
    en: "Today we connect people across every language.",
    t: { hi: "आज हम हर भाषा में लोगों को जोड़ते हैं।", es: "Hoy conectamos a las personas en todos los idiomas.", ja: "今日、私たちはあらゆる言語で人々をつなぎます。", ar: "اليوم نربط الناس عبر كل لغة.", fr: "Aujourd'hui, nous connectons les gens dans toutes les langues.", zh: "今天我们跨越每一种语言连接人们。" },
  },
  {
    en: "Real-time understanding, for everyone.",
    t: { hi: "वास्तविक समय में समझ, सबके लिए।", es: "Comprensión en tiempo real, para todos.", ja: "リアルタイムの理解を、すべての人に。", ar: "فهم فوري، للجميع.", fr: "Une compréhension en temps réel, pour tous.", zh: "为每个人提供实时理解。" },
  },
];

export default function Playground() {
  const [tab, setTab] = useState("mic");
  const [sourceLang, setSourceLang] = useState("auto");
  const [sttModel] = useState("faster-whisper");
  const [enableTranslation, setEnableTranslation] = useState(true);
  const [translationModel, setTranslationModel] = useState("nllb-200");
  const [targets, setTargets] = useState(["hi", "es", "ja"]);
  const [enableTTS, setEnableTTS] = useState(false);
  const [ttsModel, setTtsModel] = useState("supertonic");

  const [fileName, setFileName] = useState("");
  const [link, setLink] = useState("");
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const [running, setRunning] = useState(false);
  const [feed, setFeed] = useState([]);

  const mediaRef = useRef(null);
  const timerRef = useRef(null);
  const feedRef = useRef(null);

  const toggleTarget = (code) =>
    setTargets((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );

  // Microphone capture (browser-based)
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      mediaRef.current = { rec, stream };
      rec.start();
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
      toast.success("Microphone connected, capturing audio");
    } catch (e) {
      toast.error("Microphone access denied. Check browser permissions.");
    }
  };

  const stopRecording = () => {
    const m = mediaRef.current;
    if (m) {
      m.rec.stop();
      m.stream.getTracks().forEach((t) => t.stop());
      mediaRef.current = null;
    }
    clearInterval(timerRef.current);
    setRecording(false);
  };

  useEffect(() => () => {
    clearInterval(timerRef.current);
    if (mediaRef.current) {
      mediaRef.current.stream.getTracks().forEach((t) => t.stop());
    }
  }, []);

  const inputReady =
    (tab === "mic") ||
    (tab === "file" && fileName) ||
    (tab === "link" && link.trim().length > 5);

  const runPipeline = () => {
    if (!inputReady) {
      toast.error("Add an input first (record, upload a file, or paste a link).");
      return;
    }
    if (enableTranslation && targets.length === 0) {
      toast.error("Select at least one target language.");
      return;
    }
    setFeed([]);
    setRunning(true);
    toast.info("Demo mode: streaming a sample result. Connect your SUSI backend for live inference.");
    let i = 0;
    const push = () => {
      if (i >= SEGMENTS.length) {
        setRunning(false);
        return;
      }
      setFeed((f) => [...f, SEGMENTS[i]]);
      i += 1;
      setTimeout(push, 2200);
    };
    setTimeout(push, 700);
  };

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [feed]);

  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;

  return (
    <div className="min-h-screen bg-slate-50" data-testid="playground-page">
      {/* top bar */}
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3.5 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5" data-testid="pg-logo">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#0a52ff] text-white">
              <Languages className="h-4 w-4" />
            </span>
            <span className="font-display text-base font-extrabold tracking-tight">
              SUSI<span className="text-[#0a52ff]">.</span>Translator
            </span>
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-600 sm:flex">
              <Sparkles className="h-3.5 w-3.5" /> Demo mode
            </span>
            <Link to="/" className="hidden items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-slate-900 sm:flex">
              <ArrowLeft className="h-4 w-4" /> Home
            </Link>
            <Button
              variant="outline"
              className="rounded-full"
              data-testid="pg-signin-btn"
              onClick={() => toast("Sign-in connects to your SUSI backend, wiring pending.", { icon: "🔒" })}
            >
              <Lock className="h-4 w-4" /> Sign in
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-5 py-10 sm:px-6">
        <div className="mb-8">
          <h1 className="font-display text-4xl font-black tracking-tighter text-slate-900 sm:text-5xl">
            Playground
          </h1>
          <p className="mt-2 max-w-2xl text-slate-600">
            Configure a real-time run: choose an input, pick your models, and stream
            transcription, translation and speech. Sign in to run live inference on your SUSI backend.
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-[420px_1fr]">
          {/* CONFIG */}
          <div className="rounded-[1.75rem] border border-slate-200 bg-white p-6" data-testid="pg-config">
            <h2 className="font-display text-lg font-bold text-slate-900">Configuration</h2>

            {/* input type */}
            <div className="mt-5">
              <Label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Input source
              </Label>
              <Tabs value={tab} onValueChange={setTab} className="mt-2">
                <TabsList className="grid w-full grid-cols-3" data-testid="pg-input-tabs">
                  <TabsTrigger value="mic" data-testid="pg-tab-mic">
                    <Mic className="mr-1.5 h-4 w-4" /> Mic
                  </TabsTrigger>
                  <TabsTrigger value="file" data-testid="pg-tab-file">
                    <Upload className="mr-1.5 h-4 w-4" /> File
                  </TabsTrigger>
                  <TabsTrigger value="link" data-testid="pg-tab-link">
                    <Link2 className="mr-1.5 h-4 w-4" /> Link
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="mic" className="mt-4">
                  <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6">
                    <button
                      onClick={recording ? stopRecording : startRecording}
                      className={`flex h-16 w-16 items-center justify-center rounded-full text-white transition-all ${
                        recording ? "bg-red-500 animate-pulse" : "bg-[#0a52ff] hover:scale-105"
                      }`}
                      data-testid="pg-mic-btn"
                    >
                      {recording ? <Square className="h-6 w-6" /> : <Mic className="h-6 w-6" />}
                    </button>
                    <span className="text-sm font-medium text-slate-700" data-testid="pg-mic-status">
                      {recording ? `Recording · ${mmss}` : "Tap to record from your mic"}
                    </span>
                  </div>
                </TabsContent>

                <TabsContent value="file" className="mt-4">
                  <label
                    className="flex cursor-pointer flex-col items-center gap-2 rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center hover:border-[#0a52ff]"
                    data-testid="pg-file-drop"
                  >
                    <Upload className="h-6 w-6 text-[#0a52ff]" />
                    <span className="text-sm font-medium text-slate-700">
                      {fileName || "Upload .mp3, .wav or audio"}
                    </span>
                    <span className="text-xs text-slate-400">Click to browse</span>
                    <input
                      type="file"
                      accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac"
                      className="hidden"
                      data-testid="pg-file-input"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) {
                          setFileName(f.name);
                          toast.success(`Loaded ${f.name}`);
                        }
                      }}
                    />
                  </label>
                </TabsContent>

                <TabsContent value="link" className="mt-4">
                  <Input
                    value={link}
                    onChange={(e) => setLink(e.target.value)}
                    placeholder="https://event.m3u8 · vimeo.com/… · twitch.tv/…"
                    data-testid="pg-link-input"
                  />
                  <p className="mt-2 text-xs text-slate-400">Supports HLS .m3u8, Vimeo and Twitch.</p>
                </TabsContent>
              </Tabs>
            </div>

            {/* source language */}
            <div className="mt-6">
              <Label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Source language
              </Label>
              <Select value={sourceLang} onValueChange={setSourceLang}>
                <SelectTrigger className="mt-2" data-testid="pg-source-lang">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SOURCE_LANGS.map((l) => (
                    <SelectItem key={l.code} value={l.code}>{l.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* transcription model */}
            <div className="mt-6">
              <Label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Transcription model
              </Label>
              <Select value={sttModel} disabled>
                <SelectTrigger className="mt-2" data-testid="pg-stt-model">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="faster-whisper">faster-whisper</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* translation */}
            <div className="mt-6 rounded-2xl border border-slate-100 bg-slate-50/60 p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Languages className="h-4 w-4 text-[#0a52ff]" />
                  <span className="text-sm font-semibold text-slate-900">Enable translation</span>
                </div>
                <Switch
                  checked={enableTranslation}
                  onCheckedChange={setEnableTranslation}
                  data-testid="pg-toggle-translation"
                />
              </div>
              <AnimatePresence>
                {enableTranslation && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="mt-4">
                      <Label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Translation model
                      </Label>
                      <Select value={translationModel} onValueChange={setTranslationModel}>
                        <SelectTrigger className="mt-2 bg-white" data-testid="pg-translation-model">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="nllb-200">NLLB-200</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="mt-4">
                      <Label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Target languages
                      </Label>
                      <div className="mt-2 flex flex-wrap gap-2" data-testid="pg-targets">
                        {TARGETS.map((t) => (
                          <button
                            key={t.code}
                            onClick={() => toggleTarget(t.code)}
                            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                              targets.includes(t.code)
                                ? "border-[#0a52ff] bg-[#0a52ff] text-white"
                                : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                            }`}
                            data-testid={`pg-target-${t.code}`}
                          >
                            <img src={`https://flagcdn.com/w20/${t.country}.png`} alt={t.name} className="inline-block w-4 rounded-[2px]" /> {t.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* TTS */}
            <div className="mt-4 rounded-2xl border border-slate-100 bg-slate-50/60 p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Volume2 className="h-4 w-4 text-[#0a52ff]" />
                  <span className="text-sm font-semibold text-slate-900">Enable text-to-speech</span>
                </div>
                <Switch checked={enableTTS} onCheckedChange={setEnableTTS} data-testid="pg-toggle-tts" />
              </div>
              <AnimatePresence>
                {enableTTS && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="mt-4">
                      <Label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        TTS model
                      </Label>
                      <Select value={ttsModel} onValueChange={setTtsModel}>
                        <SelectTrigger className="mt-2 bg-white" data-testid="pg-tts-model">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="supertonic">Supertonic</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <Button
              onClick={runPipeline}
              disabled={running}
              className="mt-6 w-full rounded-full bg-[#0a52ff] py-6 text-base font-semibold text-white hover:bg-[#0a52ff]/90"
              data-testid="pg-run-btn"
            >
              {running ? (
                <><Loader2 className="h-5 w-5 animate-spin" /> Streaming…</>
              ) : (
                <><Play className="h-5 w-5 fill-current" /> Start pipeline</>
              )}
            </Button>
          </div>

          {/* OUTPUT */}
          <div className="rounded-[1.75rem] border border-slate-200 bg-white p-6" data-testid="pg-output">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 font-display text-lg font-bold text-slate-900">
                <Waves className="h-5 w-5 text-[#0a52ff]" /> Live output
              </h2>
              {running && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-[#0a52ff]">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-[#0a52ff]" /> Streaming
                </span>
              )}
            </div>

            <div
              ref={feedRef}
              className="mt-5 flex max-h-[560px] min-h-[420px] flex-col gap-4 overflow-y-auto pr-1"
            >
              {feed.length === 0 && !running && (
                <div className="flex flex-1 flex-col items-center justify-center py-20 text-center text-slate-400">
                  <Waves className="mb-3 h-10 w-10" />
                  <p className="text-sm">Configure your run and press <b>Start pipeline</b>.</p>
                </div>
              )}

              {feed.map((seg, idx) => (
                <motion.div
                  key={idx}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-2xl border border-slate-100 p-4"
                >
                  <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-slate-400">
                    <Mic className="h-3.5 w-3.5" /> Transcript · faster-whisper
                  </div>
                  <p className="text-base font-medium text-slate-900">{seg.en}</p>

                  {enableTranslation && targets.length > 0 && (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {TARGETS.filter((t) => targets.includes(t.code)).map((t) => (
                        <div key={t.code} className="rounded-xl bg-blue-50/50 px-3 py-2">
                          <div className="mb-0.5 flex items-center gap-1.5 text-xs font-semibold text-slate-500">
                            <img src={`https://flagcdn.com/w20/${t.country}.png`} alt={t.name} className="w-3.5 rounded-[2px]" /> {t.name}
                          </div>
                          <p dir={t.rtl ? "rtl" : "ltr"} className="text-sm text-slate-800">
                            {seg.t[t.code]}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}

                  {enableTTS && (
                    <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
                      <Volume2 className="h-3.5 w-3.5 text-[#0a52ff]" /> Speech synthesized · Supertonic
                    </div>
                  )}
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
