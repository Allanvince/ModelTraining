"use client";

import React, { useEffect, useRef, useState } from "react";
import { useLeaderboard } from "../../hooks/useLeaderboard";
import { fetchApi } from "../../lib/api";

interface UserProfile {
  userId: string;
  username: string;
  handle: string;
  email: string;
  phone: string;
  hasPaidEntryFee: boolean;
  balances: Balances;
  testsCompleted: number;
  testsRequired: number;
  stats: {
    gamesPlayed: number;
    passRatePercent: number;
    avgResponseMs: number;
    currentStreak: number;
    bestStreak: number;
  };
}

interface PoolStatus {
  balance: number;
  lifetimeFundedCents: number;
  lifetimePaidCents: number;
}

interface Category {
  id: string;
  questions: number;
  name?: string;
  description?: string;
  difficulty?: string;
  sample?: string;
}

interface QuestionPayload {
  sessionId: string;
  questionId: string;
  index: number;
  total: number;
  text: string;
  options: string[];
  timerMs: number;
  remainingMs: number;
  finished?: boolean;
}

interface GameSummary {
  sessionId: string;
  category: string;
  correct: number;
  total: number;
  accuracyPercent: number;
  pointsEarned: number;
  payout: number;
  net: number;
  throttled: boolean;
  isAccountLocked: boolean;
  isTest: boolean;
}

interface Balances {
  withdrawableCents: number;
  nonWithdrawableCents: number;
  reservedCents: number;
  totalCents: number;
}

interface AnswerResult {
  correct: boolean;
  reason: "CORRECT" | "WRONG" | "TIMEOUT";
  correctIdx: number;
  responseMs: number;
  pointsEarned: number;
  deltaCents: number;
  balances: Balances;
  streak: number;
  finished: boolean;
  summary: GameSummary | null;
}

// Clean up '@' handler prefix from user display names
function formatDisplayName(name?: string) {
  if (!name) return "Annotator";
  return name.startsWith("@") ? name.slice(1) : name;
}

// Hosted Gamified Animated Assets
const MASCOT_ASSETS = {
  heroMascot: "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExM3Z6Nm9xZ2JqY3R4a3p6bm9xZ2JqY3R4a3p6bm9xZ2JqY3R4YSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9cw/3o7TKSjRrfIPjeiVyM/giphy.gif",
  thinking: "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExM3Z6Nm9xZ2JqY3R4a3p6bm9xZ2JqY3R4a3p6bm9xZ2JqY3R4YSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9cw/3o7TKSjRrfIPjeiVyM/giphy.gif",
  correct: "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExb2Nza2UxcWttZHp4ZXl0d3RzZGVzaXp3YTFpeW01bmhyZ253aHRpZCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9cw/13CoXDiaCcCoyk/giphy.gif",
  wrong: "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExaG9iNW5pNXh2bnB3bjR2aDliMG1xeWF0dWc1OHk1bnZxdW04enZ2YyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9cw/d2W7eZX5z62ziqdi/giphy.gif",
  fire: "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExOHgzZGF4NW84NXEwbHByOWxqaXpwbWlxeXlxcTRybXpsNndxeW9ndSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9cw/Lopx9eUi34rbq/giphy.gif",
  trophy: "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExYmt6MjhpeWprOHdtOGE0YXZwb2MwdmV3OHhpdHJxMGZxa2pwaWRlMiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9cw/26u4cqiYI30juCOGY/giphy.gif"
};

export default function Dashboard() {
  const [view, setView] = useState<"AUTH" | "HUB" | "GAME" | "SUMMARY">("AUTH");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");

  // Auth Form State
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("254708374149");
  const [password, setPassword] = useState("");

  // App Data State
  const [user, setUser] = useState<UserProfile | null>(null);
  const [pool, setPool] = useState<PoolStatus | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [message, setMessage] = useState("");
  const [depositAmount, setDepositAmount] = useState(100);

  // Active Game State
  const [selectedCategory, setSelectedCategory] = useState("tech");
  const [customTopic, setCustomTopic] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState<QuestionPayload | null>(null);
  const [selectedChoice, setSelectedChoice] = useState<number | null>(null);
  const [gameSummary, setGameSummary] = useState<GameSummary | null>(null);
  const [remainingMs, setRemainingMs] = useState(0);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [stopwatchMs, setStopwatchMs] = useState(0);
  const deadlineRef = useRef(0);

  // Modal State
  const [previewCategory, setPreviewCategory] = useState<Category | null>(null);

  const { leaderboard, connected } = useLeaderboard();

  // Live Stopwatch Effect
  useEffect(() => {
    if (!currentQuestion || result) return;

    const startTime = Date.now();
    setStopwatchMs(0);

    const intervalId = setInterval(() => {
      setStopwatchMs(Date.now() - startTime);
    }, 10);

    return () => clearInterval(intervalId);
  }, [currentQuestion, result]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      loadUserData();
      setView("HUB");
    }
  }, []);

  useEffect(() => {
    if (!currentQuestion || result) return;
    deadlineRef.current = Date.now() + currentQuestion.remainingMs;
    setRemainingMs(currentQuestion.remainingMs);
    const id = setInterval(() => {
      const left = Math.max(0, deadlineRef.current - Date.now());
      setRemainingMs(left);
      if (left === 0) {
        clearInterval(id);
        submitAnswer(-1);
      }
    }, 100);
    return () => clearInterval(id);
  }, [currentQuestion, result]);

  async function loadUserData() {
    try {
      const [uData, pData, cData] = await Promise.all([
        fetchApi<UserProfile>("/me"),
        fetchApi<PoolStatus>("/pool"),
        fetchApi<Category[]>("/categories"),
      ]);
      setUser(uData);
      setPool(pData);
      setCategories(cData);
    } catch (err: any) {
      setMessage(`Auth Error: ${err.message}`);
      localStorage.removeItem("token");
      setView("AUTH");
    }
  }

  async function handleAuth(e: React.FormEvent) {
    e.preventDefault();
    setMessage("");
    try {
      const endpoint = authMode === "register" ? "/auth/register" : "/auth/login";
      const body = authMode === "register" 
        ? { username, email, phone, password } 
        : { email, password };

      const res = await fetchApi<{ token: string; user: UserProfile }>(endpoint, {
        method: "POST",
        body: JSON.stringify(body),
      });

      localStorage.setItem("token", res.token);
      setUser(res.user);
      setView("HUB");
      loadUserData();
    } catch (err: any) {
      setMessage(`Error: ${err.message}`);
    }
  }

  async function handleDeposit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await fetchApi("/dev/topup", { method: "POST" });
      await loadUserData();
      setMessage("DEV MODE: entry fee credited.");
    } catch (err: any) {
      setMessage(`Top-up failed: ${err.message}`);
    }
  }

  async function startGame(categoryId?: string) {
    const catToStart = categoryId || selectedCategory;
    setCurrentQuestion(null); 
    setResult(null); 
    setMessage("");
    setStopwatchMs(0);
    setMessage("Initializing Human Alignment Batch...");
    try {
      const res = await fetchApi<{ sessionId: string }>("/game/start", {
        method: "POST",
        body: JSON.stringify({ 
          category: catToStart, 
          topic: catToStart === "custom" ? customTopic : undefined 
        }),
      });
      setSessionId(res.sessionId);
      fetchNextQuestion(res.sessionId);
      setView("GAME");
    } catch (err: any) {
      setMessage(`Failed to start training: ${err.message}`);
    }
  }

  async function fetchNextQuestion(sId: string) {
    try {
      const q = await fetchApi<any>(`/game/${sId}/next`, { method: "POST" });
      if (q.finished) {
        finishGame(sId);
      } else {
        setCurrentQuestion(q);
        setSelectedChoice(null);
      }
    } catch (err: any) {
      setMessage(`Error pulling next prompt: ${err.message}`);
    }
  }

  async function submitAnswer(choice: number) {
    if (!sessionId || !currentQuestion || submitting || result) return;
    setSubmitting(true);
    try {
      const res = await fetchApi<AnswerResult>(`/game/${sessionId}/answer`, {
        method: "POST",
        body: JSON.stringify({ question_id: currentQuestion.questionId, choice }),
      });
      setResult(res);
      setUser((u) => (u ? { ...u, balances: res.balances } : u));
    } catch (err: any) {
      setMessage(`Submission error: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  function continueAfterResult() {
    const r = result;
    setResult(null);
    setSelectedChoice(null);
    if (r?.finished && r.summary) {
      setGameSummary(r.summary);
      setView("SUMMARY");
      loadUserData();
    } else if (sessionId) {
      fetchNextQuestion(sessionId);
    }
  }

  function formatStopwatch(ms: number): string {
    const seconds = (ms / 1000).toFixed(2);
    return `${seconds}s`;
  }

  async function finishGame(sId: string) {
    try {
      const summary = await fetchApi<GameSummary>(`/game/${sId}/summary`);
      setGameSummary(summary);
      setView("SUMMARY");
      loadUserData();
    } catch (err: any) {
      setMessage(`Failed to retrieve batch summary: ${err.message}`);
    }
  }

  function handleLogout() {
    localStorage.removeItem("token");
    setUser(null);
    setView("AUTH");
  }

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-6 flex flex-col items-center selection:bg-orange-500 selection:text-white">
      {/* QuickTrain Header */}
      <header className="w-full max-w-5xl flex justify-between items-center py-4 border-b border-zinc-800/80 mb-8">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-orange-600/20 border border-orange-500/40 flex items-center justify-center text-orange-500 shadow-lg shadow-orange-600/20">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-black text-zinc-100 tracking-wider">QUICK<span className="text-orange-500">TRAIN</span></h1>
            <p className="text-[10px] text-zinc-400 tracking-wide font-mono uppercase">Human Cognition RLHF Engine</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <span className={`text-xs px-3 py-1 rounded-full font-mono text-[11px] font-medium flex items-center gap-2 ${connected ? 'bg-orange-500/10 text-orange-400 border border-orange-500/30' : 'bg-rose-500/10 text-rose-400 border border-rose-500/30'}`}>
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-orange-500 animate-pulse' : 'bg-rose-500'}`} />
            {connected ? "MODEL NODE LIVE" : "DISCONNECTED"}
          </span>
          {user && (
            <div className="flex items-center gap-3">
              <span className="text-xs text-zinc-300 font-mono bg-zinc-900 border border-zinc-800 px-3 py-1.5 rounded-lg capitalize">
                {formatDisplayName(user.username || user.handle)}
              </span>
              <button onClick={handleLogout} className="text-xs bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 border border-zinc-800 px-3 py-1.5 rounded-lg transition">
                Logout
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Message Bar */}
      {message && (
        <div className="w-full max-w-5xl bg-orange-950/30 border border-orange-500/40 text-orange-300 p-3 rounded-lg mb-6 text-xs font-mono text-center shadow-lg shadow-orange-950/20">
          {message}
        </div>
      )}

      {/* VIEW 1: AUTHENTICATION */}
      {view === "AUTH" && (
        <div className="w-full max-w-md bg-zinc-900/80 backdrop-blur border border-zinc-800/80 p-8 rounded-2xl shadow-2xl space-y-6">
          <div className="text-center space-y-2">
            <h2 className="text-2xl font-black text-zinc-100">
              {authMode === "login" ? "Annotator Login" : "Join Training Collective"}
            </h2>
            <p className="text-xs text-zinc-400">Contribute human pressure-response benchmarks to fine-tune local models.</p>
          </div>

          <form onSubmit={handleAuth} className="space-y-4">
            {authMode === "register" && (
              <div>
                <label className="text-xs text-zinc-400 font-medium">Annotator Username</label>
                <input 
                  type="text" 
                  required 
                  value={username} 
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-zinc-100 mt-1 focus:border-orange-500 outline-none transition text-sm"
                />
              </div>
            )}
            <div>
              <label className="text-xs text-zinc-400 font-medium">Work Email</label>
              <input 
                type="email" 
                required 
                value={email} 
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-zinc-100 mt-1 focus:border-orange-500 outline-none transition text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400 font-medium">Security Password</label>
              <input 
                type="password" 
                required 
                value={password} 
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-zinc-100 mt-1 focus:border-orange-500 outline-none transition text-sm"
              />
            </div>
            <button type="submit" className="w-full bg-orange-600 hover:bg-orange-500 text-white font-bold py-3 rounded-lg mt-2 transition shadow-lg shadow-orange-600/20">
              {authMode === "login" ? "Access Annotator Dashboard" : "Create Annotator Profile"}
            </button>
          </form>

          <div className="text-center pt-2 border-t border-zinc-800/80">
            <button 
              onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
              className="text-xs text-zinc-400 hover:text-orange-400 transition"
            >
              {authMode === "login" ? "New human annotator? Register profile" : "Existing annotator? Authenticate"}
            </button>
          </div>
        </div>
      )}

      {/* VIEW 2: DASHBOARD HUB */}
      {view === "HUB" && user && (
        <div className="w-full max-w-5xl space-y-6 animate-in fade-in zoom-in-95 duration-200">
          
          {/* GAMIFIED PROFILE HEADER CARD */}
          <div className="bg-zinc-900/90 border border-zinc-800 rounded-3xl p-5 shadow-2xl relative overflow-hidden backdrop-blur-md">
            <div className="absolute -top-10 -left-10 w-36 h-36 bg-orange-500/10 rounded-full blur-3xl pointer-events-none" />

            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="relative">
                  <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-orange-500/20 to-zinc-950 border border-orange-500/40 p-1 flex items-center justify-center shadow-lg shadow-orange-950/40">
                    <img
                      src={MASCOT_ASSETS.heroMascot}
                      alt="Profile Mascot"
                      className="w-full h-full object-contain"
                    />
                  </div>
                  <div className="absolute -bottom-1 -right-1 bg-orange-500 text-zinc-950 text-[10px] font-black font-mono px-1.5 py-0.5 rounded-md shadow">
                    LVL 12
                  </div>
                </div>

                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-zinc-100 capitalize">
                      {formatDisplayName(user?.username || user?.handle)}
                    </h2>
                    <span className="text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full font-mono font-medium">
                      Online
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 font-mono">
                    Prompt Alignment Specialist
                  </p>
                </div>
              </div>

              <div className="flex flex-col items-end gap-1">
                <div className="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-xl">
                  <img src={MASCOT_ASSETS.fire} alt="Streak" className="w-4 h-4 object-contain" />
                  <span className="text-xs font-mono font-bold text-orange-400">
                    {user?.stats?.currentStreak || 0} Streak
                  </span>
                </div>
                <span className="text-[10px] text-zinc-500 font-mono">
                  Best: {user?.stats?.bestStreak || 0} 🔥
                </span>
              </div>
            </div>
          </div>

          {/* PLAYFUL HERO BANNER */}
          <div className="bg-gradient-to-r from-orange-950/40 via-zinc-900 to-zinc-900 border border-orange-500/30 rounded-3xl p-6 relative overflow-hidden flex items-center justify-between gap-4 shadow-xl">
            <div className="space-y-2 max-w-sm">
              <div className="inline-flex items-center gap-2 bg-orange-500/10 border border-orange-500/20 px-3 py-1 rounded-full text-[11px] font-mono text-orange-400">
                <span>🎮 High-Velocity RLHF Engine</span>
              </div>
              <h1 className="text-2xl font-black text-zinc-100 tracking-tight">
                Ready to align human-level prompts?
              </h1>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Inspect active training batches, submit high-precision responses, and earn streak bounties.
              </p>
            </div>

            <div className="w-24 h-24 flex-shrink-0 hidden sm:flex items-center justify-center bg-zinc-950/60 border border-zinc-800 rounded-2xl p-2 shadow-inner">
              <img
                src={MASCOT_ASSETS.heroMascot}
                alt="Dashboard Mascot"
                className="w-full h-full object-contain animate-pulse"
              />
            </div>
          </div>

          {/* MAIN DASHBOARD CONTENT GRID */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            
            {/* Wallet & Compute Stake */}
            <div className="bg-zinc-900/90 border border-zinc-800/80 rounded-2xl p-5 space-y-5 h-fit shadow-xl">
              <div>
                <h3 className="text-base font-bold text-zinc-200">Compute Stake & Bounties</h3>
                <p className="text-[11px] text-zinc-400">High-speed dataset annotation rewards.</p>
              </div>

              <div className="bg-zinc-950 p-4 rounded-xl border border-zinc-800/60 space-y-2.5 font-mono">
                <div className="flex justify-between text-xs">
                  <span className="text-zinc-400">Claimable Rewards:</span>
                  <span className="text-emerald-400 font-bold">${(user.balances.withdrawableCents / 100).toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-zinc-400">Total Compute Balance:</span>
                  <span className="text-orange-400 font-bold">${(user.balances.totalCents / 100).toFixed(2)}</span>
                </div>
              </div>

              <form onSubmit={handleDeposit} className="space-y-3 pt-1 border-t border-zinc-800/80">
                <h4 className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider font-mono">M-Pesa Compute Refill</h4>
                <div>
                  <label className="text-[11px] text-zinc-500">Mobile Number</label>
                  <input 
                    type="text" 
                    value={phone} 
                    onChange={(e) => setPhone(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 mt-1 font-mono outline-none focus:border-orange-500"
                  />
                </div>
                <div>
                  <label className="text-[11px] text-zinc-500">Amount (KES)</label>
                  <input 
                    type="number" 
                    value={depositAmount} 
                    onChange={(e) => setDepositAmount(Number(e.target.value))}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 mt-1 font-mono outline-none focus:border-orange-500"
                  />
                </div>
                <button type="submit" className="w-full bg-zinc-100 hover:bg-white text-zinc-950 font-bold py-2.5 rounded-lg text-xs transition shadow-md">
                  Top Up via M-Pesa
                </button>
              </form>
            </div>

            {/* Training Benchmarks & Pipelines */}
            <div className="bg-zinc-900/90 border border-zinc-800/80 rounded-2xl p-5 space-y-6 md:col-span-2 shadow-xl">
              <div>
                <h3 className="text-base font-bold text-zinc-200 mb-0.5">Dataset Training Pipelines</h3>
                <p className="text-xs text-zinc-400 mb-4">Choose a domain pipeline to submit high-pressure response telemetry.</p>
                
                {/* Category Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {categories.map((c) => (
                    <div
                      key={c.id}
                      onClick={() => {
                        setSelectedCategory(c.id);
                        setPreviewCategory(c);
                      }}
                      className={`p-4 rounded-xl border transition cursor-pointer flex flex-col justify-between ${
                        selectedCategory === c.id 
                          ? "bg-orange-950/20 border-orange-500/80 shadow-lg shadow-orange-950/20" 
                          : "bg-zinc-950 border-zinc-800/80 hover:border-zinc-700"
                      }`}
                    >
                      <div>
                        <div className="flex justify-between items-center mb-1.5">
                          <span className="font-bold text-zinc-100 text-sm capitalize">{c.name || c.id}</span>
                          <span className="text-[10px] bg-zinc-800/80 text-orange-400 border border-zinc-700/50 px-2 py-0.5 rounded-full font-mono font-semibold">
                            {c.difficulty || "Medium"}
                          </span>
                        </div>
                        <p className="text-xs text-zinc-400 line-clamp-2 mb-3 leading-relaxed">
                          {c.description || "High-velocity prompt response benchmark."}
                        </p>
                      </div>
                      <div className="flex justify-between items-center text-[11px] text-zinc-500 font-mono pt-2 border-t border-zinc-900">
                        <span>{c.questions} Prompts</span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedCategory(c.id);
                            setPreviewCategory(c);
                          }}
                          className="text-orange-400 font-medium hover:underline hover:text-orange-300 transition"
                        >
                          Inspect Batch →
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                {selectedCategory === "custom" && (
                  <div className="mt-4 p-3.5 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <label className="text-xs text-zinc-400 font-mono">Custom Synthetic Prompt Context</label>
                    <input 
                      type="text" 
                      placeholder="e.g. Microservices, Organic Chemistry, African History"
                      value={customTopic}
                      onChange={(e) => setCustomTopic(e.target.value)}
                      className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2.5 text-zinc-200 mt-1 text-sm outline-none focus:border-orange-500"
                    />
                  </div>
                )}
              </div>

              {/* Leaderboard */}
              <div className="pt-4 border-t border-zinc-800/80">
                <div className="flex justify-between items-center mb-3">
                  <h4 className="text-xs font-bold text-zinc-300 font-mono uppercase tracking-wider">Top Human Velocity Annotators</h4>
                  <span className="text-[10px] text-zinc-500 font-mono">Response Latency (ms)</span>
                </div>
                <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                  {leaderboard.map((entry, idx) => (
                    <div key={idx} className="flex justify-between items-center bg-zinc-950 p-2.5 rounded-lg border border-zinc-800/60 text-xs">
                      <div className="flex items-center gap-3">
                        <span className="text-orange-500 font-mono font-bold">#{entry.rank || idx + 1}</span>
                        <span className="text-zinc-200 font-medium capitalize">
                          {formatDisplayName(entry.username || entry.username)}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 text-xs font-mono">
                        {entry.avgMs != null && (
                        <span className="text-zinc-400">{entry.avgMs}ms latency</span>
                        )}
                        <span className="text-emerald-400 font-bold">{entry.streak}🔥 streak</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* VIEW 3: RLHF TIMED BENCHMARK RUN */}
      {view === "GAME" && currentQuestion && (
        <div className="w-full max-w-2xl bg-zinc-900/90 border border-zinc-800 rounded-2xl p-6 space-y-6 shadow-2xl">
          {/* Header info with Stopwatch Counter */}
          <div className="flex justify-between items-center border-b border-zinc-800/80 pb-3 font-mono">
            <span className="text-xs text-orange-400 uppercase font-bold tracking-wider">
              Prompt {currentQuestion.index} / {currentQuestion.total}
            </span>

            {/* Stopwatch Counter Badge */}
            <div className="flex items-center gap-2 bg-zinc-950 border border-zinc-800 px-3 py-1 rounded-lg">
              <span className="w-2 h-2 rounded-full bg-orange-500 animate-ping" />
              <span className="text-xs font-mono font-bold text-zinc-200">
                ⏱️ {formatStopwatch(stopwatchMs)}
              </span>
            </div>

            <span className="text-xs text-zinc-400 uppercase">
              Pipeline: {selectedCategory}
            </span>
          </div>

          {/* Question prompt */}
          <div className="space-y-2">
            <p className="text-[11px] text-zinc-500 font-mono uppercase tracking-wider">
              Cognitive Pressure Target:
            </p>
            <h3 className="text-lg font-medium text-zinc-100 leading-relaxed">
              {currentQuestion.text}
            </h3>
          </div>

          {/* Question options */}
          <div className="space-y-3">
            {currentQuestion.options?.map((choice: string, idx: number) => {
              const isRevealed = result !== null;
              const isCorrectOption = isRevealed && idx === result.correctIdx;
              const isWrongSelection = isRevealed && idx === selectedChoice && !result.correct;

              let borderStyle = "bg-zinc-950 border-zinc-800/80 hover:border-zinc-700 text-zinc-300";

              if (isRevealed) {
                if (isCorrectOption) {
                  borderStyle = "bg-emerald-950/40 border-emerald-500 text-emerald-200 font-medium";
                } else if (isWrongSelection) {
                  borderStyle = "bg-rose-950/40 border-rose-500 text-rose-200 font-medium";
                }
              } else if (selectedChoice === idx) {
                borderStyle = "bg-orange-500/20 border-orange-500 text-orange-200 font-medium shadow-md shadow-orange-950/30";
              }

              return (
                <button
                  key={idx}
                  disabled={result !== null}
                  onClick={() => setSelectedChoice(idx)}
                  className={`w-full text-left p-4 rounded-xl border transition flex items-center justify-between text-sm ${borderStyle}`}
                >
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-bold text-xs text-orange-500">
                      {String.fromCharCode(65 + idx)}.
                    </span>
                    <span>{choice}</span>
                  </div>
                  {isCorrectOption && (
                    <span className="text-xs text-emerald-400 font-mono font-bold">
                      ✓ Correct
                    </span>
                  )}
                  {isWrongSelection && (
                    <span className="text-xs text-rose-400 font-mono font-bold">
                      ✗ Wrong
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Gamified Submission / Feedback Banner */}
          {!result ? (
            <button
              onClick={() => selectedChoice !== null && submitAnswer(selectedChoice)}
              disabled={selectedChoice === null || submitting}
              className="w-full bg-orange-600 hover:bg-orange-500 disabled:bg-zinc-800 disabled:text-zinc-600 text-white font-bold py-3.5 rounded-xl transition shadow-lg shadow-orange-600/20 flex items-center justify-center gap-2"
            >
              {submitting ? "Submitting Telemetry..." : "Submit Annotator Choice"}
            </button>
          ) : (
            <div className="space-y-3">
              <div className="bg-zinc-950 border border-zinc-800 rounded-2xl p-4 flex items-center justify-between shadow-inner">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center justify-center p-1 overflow-hidden">
                    <img
                      src={result.correct ? MASCOT_ASSETS.correct : MASCOT_ASSETS.wrong}
                      alt="Feedback Mascot"
                      className="w-full h-full object-contain"
                    />
                  </div>

                  <div>
                    <span className={`text-sm font-bold block ${result.correct ? "text-emerald-400" : "text-rose-400"}`}>
                      {result.reason === "TIMEOUT"
                        ? "⏱️ Time's Up!"
                        : result.correct
                        ? `🎉 Correct! +${result.pointsEarned} pts`
                        : "😅 Ouch, Missed It!"}
                    </span>
                    <span className="text-xs text-zinc-400 font-mono">
                      {result.deltaCents !== 0 ? `${(result.deltaCents / 100).toFixed(2)} USD` : "no charge"} · {result.responseMs}ms
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 bg-orange-950/30 border border-orange-500/30 px-3 py-1.5 rounded-xl">
                  <img src={MASCOT_ASSETS.fire} alt="Streak Fire" className="w-5 h-5 object-contain" />
                  <span className="text-orange-400 font-mono font-bold text-xs">{result.streak} Streak</span>
                </div>
              </div>

              <button
                onClick={continueAfterResult}
                className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3.5 rounded-xl transition shadow-lg shadow-emerald-600/20"
              >
                {result.finished ? "See Summary →" : "Next Prompt →"}
              </button>
            </div>
          )}
        </div>
      )}

      {/* VIEW 4: BATCH TRAINING SUMMARY */}
      {view === "SUMMARY" && gameSummary && (
        <div className="w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-6 text-center shadow-2xl">
          <div className="w-20 h-20 mx-auto rounded-2xl bg-zinc-950 border border-zinc-800 p-2 flex items-center justify-center shadow-inner">
            <img src={MASCOT_ASSETS.trophy} alt="Trophy" className="w-full h-full object-contain" />
          </div>
          <div className="space-y-1">
            <h2 className="text-xl font-black text-orange-500">Batch Alignment Complete</h2>
            <p className="text-xs text-zinc-400">Response telemetry successfully recorded.</p>
          </div>
          
          <div className="bg-zinc-950 p-4 rounded-xl border border-zinc-800/80 space-y-3 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-zinc-400">Human Accuracy:</span>
              <span className="text-emerald-400 font-bold">{gameSummary.correct} / {gameSummary.total}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Alignment Score:</span>
              <span className="text-orange-400 font-bold">{gameSummary.accuracyPercent}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Annotator Reward Points:</span>
              <span className="text-orange-400 font-bold">{gameSummary.pointsEarned} pts</span>
            </div>
            <div className="flex justify-between pt-2 border-t border-zinc-900">
              <span className="text-zinc-400">Net Bounty Earned:</span>
              <span className={`font-bold ${gameSummary.net >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                ${gameSummary.net.toFixed(2)}
              </span>
            </div>
          </div>

          <button
            onClick={() => setView("HUB")}
            className="w-full bg-orange-600 hover:bg-orange-500 text-white font-bold py-3 rounded-xl transition shadow-lg shadow-orange-600/20 text-xs"
          >
            Return to Pipeline Hub
          </button>
        </div>
      )}

      {/* PREVIEW BATCH MODAL */}
      {previewCategory && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-3xl p-6 max-w-md w-full space-y-5 shadow-2xl relative overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            
            <div className="absolute -top-12 -right-12 w-32 h-32 bg-orange-500/10 rounded-full blur-2xl pointer-events-none" />

            <div className="flex items-start justify-between border-b border-zinc-800/80 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-14 h-14 rounded-2xl bg-zinc-950 border border-zinc-800 p-1 flex items-center justify-center shadow-inner overflow-hidden flex-shrink-0">
                  <img
                    src={MASCOT_ASSETS.thinking}
                    alt="Thinking Mascot"
                    className="w-full h-full object-contain"
                  />
                </div>

                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-zinc-100 capitalize">
                      {previewCategory.name || previewCategory.id}
                    </h3>
                    <span className="text-[10px] bg-orange-500/10 text-orange-400 border border-orange-500/30 px-2 py-0.5 rounded-full font-mono font-bold">
                      {previewCategory.difficulty || "Medium"}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 font-mono">
                    ⚡ {previewCategory.questions} Prompts in Batch
                  </p>
                </div>
              </div>

              <button
                onClick={() => setPreviewCategory(null)}
                className="text-zinc-500 hover:text-zinc-300 text-lg font-bold px-2 py-1 rounded-lg transition hover:bg-zinc-800/60"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3.5">
              <div>
                <h4 className="text-[11px] font-mono uppercase text-orange-400 font-bold mb-1 tracking-wider">
                  🎯 Pipeline Mission
                </h4>
                <p className="text-xs text-zinc-300 leading-relaxed">
                  {previewCategory.description ||
                    "High-velocity prompt response benchmark. Submit speed-optimized response choices to align real-time model preferences."}
                </p>
              </div>

              {previewCategory.sample && (
                <div className="bg-zinc-950 border border-zinc-800 rounded-2xl p-3.5 space-y-1.5 shadow-inner">
                  <div className="flex justify-between items-center">
                    <h5 className="text-[10px] font-mono uppercase text-zinc-500 font-semibold">
                      Sample Prompt Target
                    </h5>
                    <span className="text-[10px] text-orange-400/80 font-mono">Telemetry Target</span>
                  </div>
                  <p className="text-xs font-mono text-zinc-300 italic bg-zinc-900/50 p-2.5 rounded-xl border border-zinc-800/50">
                    "{previewCategory.sample}"
                  </p>
                </div>
              )}

              <div className="bg-orange-950/20 border border-orange-500/30 rounded-xl p-3 flex items-center justify-between text-xs font-mono">
                <span className="text-zinc-400">Streak Bonus Rate:</span>
                <span className="text-orange-400 font-bold flex items-center gap-1">
                  <img src={MASCOT_ASSETS.fire} alt="Fire" className="w-4 h-4 object-contain inline" />
                  Up to 1.5x Bounty
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={() => setPreviewCategory(null)}
                className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-medium py-3 rounded-xl text-xs transition"
              >
                Close
              </button>
              <button
                onClick={() => {
                  const catId = previewCategory.id;
                  setPreviewCategory(null);
                  startGame(catId);
                }}
                className="flex-1 bg-orange-600 hover:bg-orange-500 text-white font-bold py-3 rounded-xl text-xs transition shadow-lg shadow-orange-600/20 flex items-center justify-center gap-1.5"
              >
                <span>Start Batch</span>
                <span>→</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}