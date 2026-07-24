import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Github, Globe } from "lucide-react";
import { Mist } from "@/components/Mist";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";

const Signup = () => {
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSignup = (e) => {
    e.preventDefault();
    login();
    navigate("/demo");
  };

  return (
    <div className="relative min-h-screen flex items-center justify-center overflow-hidden bg-white px-4 sm:px-6">
      <Mist />
      <div className="grain absolute inset-0 opacity-60" aria-hidden="true" />

      <Link
        to="/"
        className="absolute left-6 top-6 z-20 flex items-center gap-2 text-sm font-medium text-slate-500 transition-colors hover:text-slate-900"
      >
        <ArrowLeft className="h-4 w-4" /> Back to home
      </Link>

      {/* Strong orb directly behind the card to make the glass blur stand out */}
      <motion.div 
        animate={{ scale: [1, 1.1, 1], rotate: [0, 90, 0] }}
        transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
        className="absolute top-1/2 left-1/2 h-[400px] w-[400px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-tr from-blue-500/40 to-cyan-300/40 blur-[80px]" 
      />

      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        className="glass relative z-10 w-full max-w-[440px] rounded-3xl p-8 sm:p-12"
      >
        <div className="flex justify-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#0a52ff] text-white shadow-xl shadow-blue-500/20">
            <Globe className="h-6 w-6" />
          </span>
        </div>

        <div className="mt-8 text-center">
          <h1 className="font-display text-3xl font-bold tracking-tight text-slate-900">
            Create an account
          </h1>
          <p className="mt-3 text-slate-500">
            Join SUSI Translator and break language barriers today.
          </p>
        </div>

        <div className="mt-8">
          <Button
            variant="outline"
            className="w-full justify-center gap-2 rounded-xl py-6 text-base font-semibold"
            onClick={handleSignup}
          >
            <Github className="h-5 w-5" /> Sign up with GitHub
          </Button>

          <div className="my-8 flex items-center gap-4 before:h-px before:flex-1 before:bg-slate-200 after:h-px after:flex-1 after:bg-slate-200">
            <span className="text-xs uppercase tracking-wider text-slate-400">or</span>
          </div>

          <form onSubmit={handleSignup} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="firstName" className="sr-only">First name</label>
                <input
                  type="text"
                  id="firstName"
                  required
                  className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-3.5 text-slate-900 placeholder:text-slate-400 focus:border-[#0a52ff] focus:outline-none focus:ring-4 focus:ring-[#0a52ff]/10"
                  placeholder="First name"
                />
              </div>
              <div>
                <label htmlFor="lastName" className="sr-only">Last name</label>
                <input
                  type="text"
                  id="lastName"
                  required
                  className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-3.5 text-slate-900 placeholder:text-slate-400 focus:border-[#0a52ff] focus:outline-none focus:ring-4 focus:ring-[#0a52ff]/10"
                  placeholder="Last name"
                />
              </div>
            </div>
            <div>
              <label htmlFor="email" className="sr-only">Email address</label>
              <input
                type="email"
                id="email"
                required
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-3.5 text-slate-900 placeholder:text-slate-400 focus:border-[#0a52ff] focus:outline-none focus:ring-4 focus:ring-[#0a52ff]/10"
                placeholder="Email address"
              />
            </div>
            <div>
              <label htmlFor="password" className="sr-only">Password</label>
              <input
                type="password"
                id="password"
                required
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-3.5 text-slate-900 placeholder:text-slate-400 focus:border-[#0a52ff] focus:outline-none focus:ring-4 focus:ring-[#0a52ff]/10"
                placeholder="Create password"
              />
            </div>
            <Button
              type="submit"
              className="mt-2 w-full rounded-xl bg-[#0a52ff] py-6 text-base font-semibold text-white shadow-[0_8px_20px_rgba(10,82,255,0.25)] transition-shadow hover:shadow-[0_12px_28px_rgba(10,82,255,0.35)]"
            >
              Create account
            </Button>
          </form>
        </div>

        <p className="mt-8 text-center text-sm text-slate-500">
          Already have an account?{" "}
          <Link to="/login" className="font-semibold text-[#0a52ff] hover:underline">
            Sign in
          </Link>
        </p>
      </motion.div>
    </div>
  );
};

export default Signup;
