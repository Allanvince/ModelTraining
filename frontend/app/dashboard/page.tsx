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
  minWithdrawCents?: number;
  kesPerUsd?: number;
  withdrawFeePercent?: number;
  depositRule?: { isFixed: boolean; fixedKes: number; minKes: number; maxKes: number };
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

interface ReviewItem {
  number: number;
  text: string;
  options: string[];
  yourIdx: number | null;
  correctIdx: number;
  timedOut: boolean;
}
interface ReviewData { total: number; wrong: ReviewItem[]; }

const PASSWORD_RULES = [
  { id: "len", label: "At least 8 characters", test: (p: string) => p.length >= 8 },
  { id: "upper", label: "One capital letter (A-Z)", test: (p: string) => /[A-Z]/.test(p) },
  { id: "lower", label: "One small letter (a-z)", test: (p: string) => /[a-z]/.test(p) },
  { id: "num", label: "One number (0-9)", test: (p: string) => /[0-9]/.test(p) },
  { id: "sym", label: "One symbol (e.g. ! @ # $)", test: (p: string) => /[^A-Za-z0-9]/.test(p) },
];

const TERMS_TEXT: { title: string; body: string }[] = [
  { title: "1. What this is", body: "Quick Train is a platform used to train local model to mimic human question answering techniques while subject to a slight kind of pressure, in this case TIME. You answer multiple-choice questions against a countdown. It is a task of knowledge and speed, and you can lose points." },
  { title: "2. Practice rounds", body: "You must finish 3 eligibility tests before you start receiving rewards. The eligibility tests have no reward, but wrong or timed-out answers will deduct points which as a result will deduct some amount from your activation fee(see Activation fee for details)." },
  { title: "3. Activation fee", body: "You pay an activation fee of $3.00 (about KES 390, via M-Pesa). 30% ($0.90) is kept by us as a non-refundable service fee. The remaining $2.10 will be converted to points and these will be your starting points. Remember when we said during the tests wrong or timed-out answers will deduct points, these were the points we were talking about. " },
  { title: "4. Rules", body: "An account has two wallets, one for withdrawables and the other for non-refundables(the non-refundables act as collateral hence the starting points meaning they can help you continue the training tasks even if you get several questions wrong). However, when the activation fee is depleted meaning your accuracy is below 5 in most categories, you will have to activate the account again to continue. "},
  { title: "5. Wrong answers cost points", body: "Each wrong or timed-out answer deducts points from your balance (from your winnings first, then your starting balance). You can lose your entire balance. If your balance reaches $0.00 your account is locked until you reactivate the account" },
  { title: "6. How winnings work", body: "Each correct answer earns 10 points, worth up to $0.50 at full rate. Points are paid at the end of a round from a shared prize pool. The pool is funded by deductions from players' wrong answers. If the pool is low, your payout is reduced and your round summary will show this." },
  { title: "7. Withdrawals", body: "You can withdraw any amount of your winnings (not your starting balance), from a minimum of $0.50, to your registered M-Pesa number. The amount is converted at KES 129 per $1. Withdrawals normally arrive within minutes; if one fails the money returns to your winnings. A small service fee is charged for teh withdrawals" },
  { title: "8. Fair play", body: "One account per person. Bots, scripts, answer-sharing and multiple accounts will lead to account closure and loss of winnings." },
  { title: "9. Age and legal", body: "You must be 18 or older. It is your responsibility to make sure playing is allowed where you live." },
  { title: "10. Your data", body: "We store your name, email, phone number and game history to run your account and pay you. We do not sell your data." },
  { title: "11. Changes and contact", body: "We will tell you before these terms change. Contact: [SUPPORT_EMAIL]." },
];

// Clean up '@' handler prefix from user display names
function formatDisplayName(name?: string) {
  if (!name) return "Player";
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
  const [showPassword, setShowPassword] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [showTerms, setShowTerms] = useState(false);
  const [withdrawAmount, setWithdrawAmount] = useState("");
  const [withdrawing, setWithdrawing] = useState(false);
  const [review, setReview] = useState<ReviewData | null>(null);

  // App Data State
  const [user, setUser] = useState<UserProfile | null>(null);
  const [pool, setPool] = useState<PoolStatus | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [message, setMessage] = useState("");
  const [depositAmount, setDepositAmount] = useState("");
  const [depositPhone, setDepositPhone] = useState("");

  // Active Game State
  const [selectedCategory, setSelectedCategory] = useState("tech");
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
  const [depositing, setDepositing] = useState(false);

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
      setDepositPhone((p) => p || uData.phone || "");
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
    if (authMode === "register") {
      if (!PASSWORD_RULES.every((r) => r.test(password))) {
        setMessage("Please choose a stronger password - see the checklist below the password box.");
        return;
      }
      if (!acceptedTerms) {
        setMessage("Please read and accept the Terms & Conditions to create an account.");
        return;
      }
    }
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
  if (depositing) return;
 
  // Dev-only shortcut. Set NEXT_PUBLIC_DEV_TOPUP=true on the DEV frontend project ONLY.
  if (process.env.NEXT_PUBLIC_DEV_TOPUP === "true") {
    try {
      await fetchApi("/dev/topup", { method: "POST" });
      await loadUserData();
      setMessage("DEV MODE: activation fee credited.");
    } catch (err: any) {
      setMessage(`Top-up failed: ${err.message}`);
    }
    return;
  }
 
  setDepositing(true);
  setMessage("Sending an M-Pesa prompt to your phone. Enter your M-Pesa PIN to confirm.");
  try {
    const rule = user?.depositRule;
    const kes = rule?.isFixed ? rule.fixedKes : parseInt(depositAmount, 10);
    if (!depositPhone.trim()) { setMessage("Enter your M-Pesa phone number."); return; }
    if (!rule?.isFixed && (!kes || kes < (rule?.minKes ?? 100))) {
      setMessage(`Minimum deposit is KES ${rule?.minKes ?? 100}.`); return;
    }
    const tx = await fetchApi<{ status: string; checkoutRequestId: string }>("/payments/deposit", {
  method: "POST",
  body: JSON.stringify({ phone: depositPhone.trim(), amount_kes: kes }),
});
 
    // Poll for up to ~2 minutes while the customer approves the prompt.
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      const s = await fetchApi<{ status: string; resultDesc: string | null }>(
        `/payments/status/${tx.checkoutRequestId}`
      );
      if (s.status === "SUCCESS") {
        await loadUserData();
        setMessage("Payment received. Your account is activated!");
        return;
      }
      if (s.status === "FAILED") {
        setMessage(`Payment was not completed${s.resultDesc ? ": " + s.resultDesc : ""}. You can try again.`);
        return;
      }
      if (s.status === "REVIEW") {
        setMessage("We received your payment but need to verify it. Please contact support if your balance does not update soon.");
        return;
      }
    }
    setMessage("Still waiting for confirmation. If you paid, your balance will update shortly. Otherwise, try again.");
  } catch (err: any) {
    setMessage(`Payment failed: ${err.message}`);
  } finally {
    setDepositing(false);
  }
}

  async function handleWithdraw(e: React.FormEvent) {
    e.preventDefault();
    const cents = Math.round(parseFloat(withdrawAmount) * 100);
    if (!cents || cents <= 0) { setMessage("Enter an amount to withdraw."); return; }
    setWithdrawing(true);
    try {
      await fetchApi("/payments/withdraw", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ amount_usd: cents / 100 }),
      });
      setWithdrawAmount("");
      await loadUserData();
      setMessage("Withdrawal sent! The money will arrive on your M-Pesa shortly.");
    } catch (err: any) {
      setMessage(`Withdrawal failed: ${err.message}`);
    } finally {
      setWithdrawing(false);
    }
  }

  async function startGame(categoryId?: string) {
    const catToStart = categoryId || selectedCategory;
    setCurrentQuestion(null); 
    setResult(null); 
    setMessage("");
    setStopwatchMs(0);
    setMessage("Getting your questions ready...");
    try {
      const res = await fetchApi<{ sessionId: string }>("/game/start", {
        method: "POST",
        body: JSON.stringify({ 
          category: catToStart, 
        }),
      });
      setSessionId(res.sessionId);
      fetchNextQuestion(res.sessionId);
      setView("GAME");
    } catch (err: any) {
      setMessage(`Could not start the round: ${err.message}`);
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
      setMessage(`Could not load the next question: ${err.message}`);
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
      setMessage(`Could not submit your answer: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function loadReview(sId: string) {
    try {
      setReview(await fetchApi<ReviewData>(`/game/${sId}/review`));
    } catch {
      setReview(null);
    }
  }

  function continueAfterResult() {
    const r = result;
    setResult(null);
    setSelectedChoice(null);
    if (r?.finished && r.summary) {
      setGameSummary(r.summary);
      if (sessionId) loadReview(sessionId);
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
      loadReview(sId);
      setView("SUMMARY");
      loadUserData();
    } catch (err: any) {
      setMessage(`Could not load your results: ${err.message}`);
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
            <h1 className="text-xl font-black text-zinc-100 tracking-wider">QUICK<span className="text-orange-500"> TRAIN</span></h1>
            <p className="text-[10px] text-zinc-400 tracking-wide font-mono uppercase">Fast Trivia. Speed, Knowledge, Earn.</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <span className={`text-xs px-3 py-1 rounded-full font-mono text-[11px] font-medium flex items-center gap-2 ${connected ? 'bg-orange-500/10 text-orange-400 border border-orange-500/30' : 'bg-rose-500/10 text-rose-400 border border-rose-500/30'}`}>
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-orange-500 animate-pulse' : 'bg-rose-500'}`} />
            {connected ? "ONLINE" : "DISCONNECTED"}
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

      {/* TERMS & CONDITIONS MODAL */}
      {showTerms && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="w-full max-w-lg max-h-[85vh] bg-zinc-900 border border-zinc-800 rounded-2xl flex flex-col">
            <div className="p-5 border-b border-zinc-800 font-bold text-zinc-100">Terms &amp; Conditions</div>
            <div className="p-5 overflow-y-auto space-y-4 text-sm text-zinc-300">
              {TERMS_TEXT.map((t) => (
                <div key={t.title}>
                  <h4 className="font-semibold text-zinc-100">{t.title}</h4>
                  <p className="text-zinc-400 text-xs leading-relaxed mt-1">{t.body}</p>
                </div>
              ))}
            </div>
            <div className="p-4 border-t border-zinc-800 flex gap-3">
              <button onClick={() => setShowTerms(false)} className="flex-1 py-2.5 rounded-lg bg-zinc-800 text-zinc-300 text-sm">Close</button>
              <button onClick={() => { setAcceptedTerms(true); setShowTerms(false); }} className="flex-1 py-2.5 rounded-lg bg-orange-600 text-white font-bold text-sm">I accept</button>
            </div>
          </div>
        </div>
      )}

      {/* VIEW 1: AUTHENTICATION */}
      {view === "AUTH" && (
        <div className="w-full max-w-md bg-zinc-900/80 backdrop-blur border border-zinc-800/80 p-8 rounded-2xl shadow-2xl space-y-6">
          <div className="text-center space-y-2">
            <h2 className="text-2xl font-black text-zinc-100">
              {authMode === "login" ? "Log in" : "Create your account"}
            </h2>
            <p className="text-xs text-zinc-400">Speed. Knowledge. Points. Money</p>
          </div>

          <form onSubmit={handleAuth} className="space-y-4">
            {authMode === "register" && (
              <div>
                <label className="text-xs text-zinc-400 font-medium">Username</label>
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
              <label className="text-xs text-zinc-400 font-medium">Email</label>
              <input 
                type="email" 
                required 
                value={email} 
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-zinc-100 mt-1 focus:border-orange-500 outline-none transition text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400 font-medium">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 pr-16 text-zinc-100 mt-1 focus:border-orange-500 outline-none transition text-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-3 top-1/2 -translate-y-1/2 mt-0.5 text-xs text-zinc-400 hover:text-orange-400"
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              {authMode === "register" && (
                <ul className="mt-2 space-y-1 text-[11px]">
                  {PASSWORD_RULES.map((r) => {
                    const ok = r.test(password);
                    return (
                      <li key={r.id} className={ok ? "text-emerald-400" : "text-zinc-500"}>
                        {ok ? "✓" : "○"} {r.label}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            {authMode === "register" && (
              <label className="flex items-start gap-2 text-xs text-zinc-400">
                <input
                  type="checkbox"
                  checked={acceptedTerms}
                  onChange={(e) => setAcceptedTerms(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  I am 18 or older and I have read and accept the{" "}
                  <button type="button" onClick={() => setShowTerms(true)} className="text-orange-400 underline">
                    Terms &amp; Conditions
                  </button>
                  .
                </span>
              </label>
            )}
            <button type="submit" disabled={authMode === "register" && (!acceptedTerms || !PASSWORD_RULES.every((r) => r.test(password)))} className="w-full bg-orange-600 hover:bg-orange-500 disabled:bg-zinc-800 disabled:text-zinc-600 text-white font-bold py-3 rounded-lg mt-2 transition shadow-lg shadow-orange-600/20">
              {authMode === "login" ? "Log in" : "Create account"}
            </button>
          </form>

          <div className="text-center pt-2 border-t border-zinc-800/80">
            <button 
              onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
              className="text-xs text-zinc-400 hover:text-orange-400 transition"
            >
              {authMode === "login" ? "New here? Create an account" : "Already have an account? Log in"}
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
                    Player
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
                <span>🎮 Fast Trivia</span>
              </div>
              <h1 className="text-2xl font-black text-zinc-100 tracking-tight">
                Ready to test your speed, knowledge and earn?
              </h1>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Pick a category, answer quickly and earn points. Keep a streak going for bonus points.
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
                <h3 className="text-base font-bold text-zinc-200">My Wallet</h3>
                <p className="text-[11px] text-zinc-400">Your balance and winnings.</p>
              </div>

              <div className="bg-zinc-950 p-4 rounded-xl border border-zinc-800/60 space-y-2.5 font-mono">
                <div className="flex justify-between text-xs">
                  <span className="text-zinc-400">Winnings you can withdraw:</span>
                  <span className="text-emerald-400 font-bold">${(user.balances.withdrawableCents / 100).toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-zinc-400">Total balance:</span>
                  <span className="text-orange-400 font-bold">${(user.balances.totalCents / 100).toFixed(2)}</span>
                </div>
              </div>

              <form onSubmit={handleWithdraw} className="space-y-2 pt-1 border-t border-zinc-800/80">
                <h4 className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider font-mono">Withdraw winnings to M-Pesa</h4>
                {user.testsCompleted < user.testsRequired ? (
                  <p className="text-[11px] text-zinc-500">
                    Finish {user.testsRequired} eligible tests to unlock withdrawals ({user.testsCompleted}/{user.testsRequired} done).
                  </p>
                ) : (
                  <>
                    <div className="flex gap-2">
                      <input
                        type="number" step="0.01" min="0" inputMode="decimal"
                        value={withdrawAmount}
                        onChange={(e) => setWithdrawAmount(e.target.value)}
                        placeholder="Amount (USD)"
                        className="flex-1 min-w-0 bg-zinc-950 border border-zinc-800 rounded-lg p-2 text-xs text-zinc-100 outline-none focus:border-orange-500"
                      />
                      <button type="button" onClick={() => setWithdrawAmount((user.balances.withdrawableCents / 100).toFixed(2))}
                        className="text-[11px] px-2 rounded-lg bg-zinc-800 text-zinc-300">Max</button>
                    </div>
                    {parseFloat(withdrawAmount) > 0 && (() => {
                      const amt = parseFloat(withdrawAmount);
                      const pct = user.withdrawFeePercent ?? 3;
                      const fee = Math.round(amt * 100 * pct / 100) / 100;
                      const net = amt - fee;
                      return (
                        <div className="text-[11px] text-zinc-500 space-y-0.5">
                          <div className="flex justify-between"><span>Service fee ({pct}%)</span><span>-${fee.toFixed(2)}</span></div>
                          <div className="flex justify-between text-zinc-300"><span>You receive</span>
                            <span>${net.toFixed(2)} ≈ KES {Math.floor(net * (user.kesPerUsd ?? 130))}</span></div>
                        </div>
                      );
                    })()}
                    <button type="submit"
                      disabled={withdrawing || user.balances.withdrawableCents < (user.minWithdrawCents ?? 50)}
                      className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-600 text-white font-bold py-2.5 rounded-lg text-xs transition">
                      {withdrawing ? "Sending..." : "Withdraw"}
                    </button>
                    <p className="text-[10px] text-zinc-600">Minimum ${((user.minWithdrawCents ?? 50) / 100).toFixed(2)}. A {user.withdrawFeePercent ?? 3}% service fee applies. Only winnings can be withdrawn.</p>
                  </>
                )}
              </form>
              <form onSubmit={handleDeposit} className="space-y-3 pt-1 border-t border-zinc-800/80">
              <input
                type="tel" inputMode="tel" value={depositPhone}
                onChange={(e) => setDepositPhone(e.target.value)}
                placeholder="0712345678"
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-xs font-mono text-zinc-200"
              />
              {user.depositRule?.isFixed ? (
                <p className="text-[11px] text-zinc-400 leading-relaxed">
                  Your non-refundable wallet is empty, so the deposit is fixed at{" "}
                  <span className="font-mono text-zinc-200">KES {user.depositRule.fixedKes}</span> ($3.00).
                </p>
              ) : (
                <>
                  <input
                    type="number" min={user.depositRule?.minKes ?? 100} step={1} value={depositAmount}
                    onChange={(e) => setDepositAmount(e.target.value)}
                    placeholder={`Amount in KES (min ${user.depositRule?.minKes ?? 100})`}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-xs font-mono text-zinc-200"
                  />
                  <p className="text-[10px] text-zinc-600">Minimum KES {user.depositRule?.minKes ?? 100}.</p>
                </>
              )}
                <button
                  type="submit"
                  disabled={depositing}
                  className="w-full bg-zinc-100 hover:bg-white disabled:bg-zinc-800 disabled:text-zinc-500 text-zinc-950 font-bold py-2.5 rounded-lg text-xs transition shadow-md"
                >
                  {depositing ? "Waiting for M-Pesa..." : "Pay with M-Pesa"}
                </button>
              </form>
            </div>

            {/* Training Benchmarks & Pipelines */}
            <div className="bg-zinc-900/90 border border-zinc-800/80 rounded-2xl p-5 space-y-6 md:col-span-2 shadow-xl">
              <div>
                <h3 className="text-base font-bold text-zinc-200 mb-0.5">Categories</h3>
                <p className="text-xs text-zinc-400 mb-4">Pick a category to start a task.</p>
                
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
                          {c.description || "Quick questions to test your knowledge."}
                        </p>
                      </div>
                      <div className="flex justify-between items-center text-[11px] text-zinc-500 font-mono pt-2 border-t border-zinc-900">
                        <span>{c.questions} questions</span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedCategory(c.id);
                            setPreviewCategory(c);
                          }}
                          className="text-orange-400 font-medium hover:underline hover:text-orange-300 transition"
                        >
                          View round →
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

              </div>

              {/* Leaderboard */}
              <div className="pt-4 border-t border-zinc-800/80">
                <div className="flex justify-between items-center mb-3">
                  <h4 className="text-xs font-bold text-zinc-300 font-mono uppercase tracking-wider">Fastest players</h4>
                  <span className="text-[10px] text-zinc-500 font-mono">Average answer time (ms)</span>
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
                        <span className="text-zinc-400">{entry.avgMs}ms avg</span>
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
              Question {currentQuestion.index} / {currentQuestion.total}
            </span>

            {/* Stopwatch Counter Badge */}
            <div className="flex items-center gap-2 bg-zinc-950 border border-zinc-800 px-3 py-1 rounded-lg">
              <span className="w-2 h-2 rounded-full bg-orange-500 animate-ping" />
              <span className="text-xs font-mono font-bold text-zinc-200">
                ⏱️ {formatStopwatch(stopwatchMs)}
              </span>
            </div>

            <span className="text-xs text-zinc-400 uppercase">
              Category: {selectedCategory}
            </span>
          </div>

          {/* Question prompt */}
          <div className="space-y-2">
            <p className="text-[11px] text-zinc-500 font-mono uppercase tracking-wider">
              Question:
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
                  disabled={result !== null || submitting}
                  onClick={() => { setSelectedChoice(idx); submitAnswer(idx); }}
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
              disabled
              className="w-full bg-zinc-800 text-zinc-500 font-bold py-3.5 rounded-xl flex items-center justify-center gap-2"
            >
              {submitting ? "Checking your answer..." : "Tap an answer to continue"}
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
                {result.finished ? "See my results →" : "Next question →"}
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
            <h2 className="text-xl font-black text-orange-500">Round complete!</h2>
            <p className="text-xs text-zinc-400">Here is how you did.</p>
          </div>
          
          <div className="bg-zinc-950 p-4 rounded-xl border border-zinc-800/80 space-y-3 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-zinc-400">Correct answers:</span>
              <span className="text-emerald-400 font-bold">{gameSummary.correct} / {gameSummary.total}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Score:</span>
              <span className="text-orange-400 font-bold">{gameSummary.accuracyPercent}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Points earned:</span>
              <span className="text-orange-400 font-bold">{gameSummary.pointsEarned} pts</span>
            </div>
            <div className="flex justify-between pt-2 border-t border-zinc-900">
              <span className="text-zinc-400">Won / lost this round:</span>
              <span className={`font-bold ${gameSummary.net >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                ${gameSummary.net.toFixed(2)}
              </span>
            </div>
          </div>

          {review && review.wrong.length > 0 && (
            <div className="text-left space-y-3">
              <h3 className="text-sm font-bold text-zinc-200">Questions to review ({review.wrong.length})</h3>
              {review.wrong.map((w) => (
                <div key={w.number} className="bg-zinc-950 border border-zinc-800 rounded-xl p-3 space-y-2">
                  <p className="text-xs text-zinc-200">Q{w.number}. {w.text}</p>
                  <p className="text-[11px] text-rose-400">
                    {w.yourIdx === null ? "You ran out of time." : `Your answer: ${w.options[w.yourIdx]}`}
                  </p>
                  <p className="text-[11px] text-emerald-400">Correct answer: {w.options[w.correctIdx]}</p>
                </div>
              ))}
            </div>
          )}
          {review && review.wrong.length === 0 && (
            <p className="text-xs text-emerald-400">Perfect round - nothing to review!</p>
          )}

          <button
            onClick={() => setView("HUB")}
            className="w-full bg-orange-600 hover:bg-orange-500 text-white font-bold py-3 rounded-xl transition shadow-lg shadow-orange-600/20 text-xs"
          >
            Back to home
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
                    ⚡ {previewCategory.questions} questions in this round
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
                  🎯 About this category
                </h4>
                <p className="text-xs text-zinc-300 leading-relaxed">
                  {previewCategory.description ||
                    "Quick questions to test your knowledge. Answer quickly to earn points."}
                </p>
              </div>

              {previewCategory.sample && (
                <div className="bg-zinc-950 border border-zinc-800 rounded-2xl p-3.5 space-y-1.5 shadow-inner">
                  <div className="flex justify-between items-center">
                    <h5 className="text-[10px] font-mono uppercase text-zinc-500 font-semibold">
                      Sample question
                    </h5>
                    <span className="text-[10px] text-orange-400/80 font-mono">Questions</span>
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
                  Streak bonus
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
                <span>Start round</span>
                <span>→</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}