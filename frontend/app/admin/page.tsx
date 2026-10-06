"use client";

import React, { useCallback, useEffect, useState } from "react";
// This file lives at <app folder>/admin/page.tsx. Adjust the path if your lib folder is elsewhere.
import { fetchApi } from "../../lib/api";

type Point = { day: string; value: number };
type Tx = { id: string; type: string; status: string; amountCents: number; amountKes: number; feeCents: number; user: string; phone: string; receipt: string | null; note: string | null; createdAt: string };
interface Overview {
  generatedAt: string; days: number; kesPerUsd: number; devMode: boolean;
  users: { total: number; new7d: number; paid: number; locked: number; active7d: number; completedPractice: number };
  money: Record<string, number>;
  games: { finished: number; practiceFinished: number; abandoned: number; accuracyPercent: number; throttledRounds: number; paidOutCents: number };
  categories: { category: string; rounds: number; accuracyPercent: number; playersNetCents: number }[];
  charts: { signups: Point[]; depositsCents: Point[]; rounds: Point[]; withdrawalsCents: Point[] };
  needsReview: Tx[]; recentTransactions: Tx[];
  topPlayers: { username: string; games: number; gamesAccuracyPercent: number; withdrawableCents: number; bestStreak: number }[];
}

const usd = (c: number) => `${c < 0 ? "-" : ""}$${(Math.abs(c) / 100).toFixed(2)}`;

function Stat({ label, value, sub, tone }: { label: string; value: string | number; sub?: string; tone?: "good" | "bad" | "warn" }) {
  const color = tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : tone === "warn" ? "text-amber-400" : "text-zinc-100";
  return (
    <div className="bg-zinc-900/90 border border-zinc-800/80 rounded-xl p-4">
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color}`}>{value}</div>
      {sub && <div className="text-[11px] text-zinc-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function Bars({ title, data, money }: { title: string; data: Point[]; money?: boolean }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const total = data.reduce((a, d) => a + d.value, 0);
  return (
    <div className="bg-zinc-900/90 border border-zinc-800/80 rounded-xl p-4">
      <div className="flex justify-between text-xs mb-3">
        <span className="font-semibold text-zinc-200">{title}</span>
        <span className="text-zinc-500">{money ? usd(total) : total} total</span>
      </div>
      <div className="flex items-end gap-1 h-24">
        {data.map((d) => (
          <div key={d.day} className="flex-1 bg-orange-500/80 hover:bg-orange-400 rounded-t min-h-[2px]"
            style={{ height: `${(d.value / max) * 100}%` }} title={`${d.day}: ${money ? usd(d.value) : d.value}`} />
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-zinc-600 mt-1">
        <span>{data[0]?.day.slice(5)}</span><span>{data[data.length - 1]?.day.slice(5)}</span>
      </div>
    </div>
  );
}

function TxTable({ rows, empty }: { rows: Tx[]; empty: string }) {
  if (!rows.length) return <p className="text-xs text-zinc-500 p-4">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-zinc-500 text-left"><tr>{["When", "User", "Type", "Status", "Amount", "Fee", "Receipt / note"].map((h) => <th key={h} className="p-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id} className="border-t border-zinc-800/70">
              <td className="p-2 text-zinc-400 whitespace-nowrap">{t.createdAt.replace("T", " ").slice(0, 16)}</td>
              <td className="p-2">{t.user}<div className="text-zinc-600">{t.phone}</div></td>
              <td className="p-2">{t.type}</td>
              <td className={`p-2 font-semibold ${t.status === "COMPLETED" ? "text-emerald-400" : t.status === "FAILED" ? "text-rose-400" : "text-amber-400"}`}>{t.status}</td>
              <td className="p-2">{usd(t.amountCents)}<div className="text-zinc-600">KES {t.amountKes}</div></td>
              <td className="p-2">{t.feeCents ? usd(t.feeCents) : "-"}</td>
              <td className="p-2 text-zinc-400 max-w-[240px] truncate" title={t.note || ""}>{t.receipt || t.note || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AdminPage() {
  const [token, setToken] = useState("");
  const [input, setInput] = useState("");
  const [days, setDays] = useState(14);
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [auto, setAuto] = useState(true);

  useEffect(() => { setToken(sessionStorage.getItem("adminToken") || ""); }, []);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setData(await fetchApi<Overview>(`/admin/overview?days=${days}`, { headers: { "X-Admin-Token": token } }));
      setError("");
    } catch (e: any) {
      setError(e.message);
      if (/token/i.test(e.message)) { sessionStorage.removeItem("adminToken"); setToken(""); }
    }
  }, [token, days]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!auto || !token) return;
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [auto, token, load]);

  if (!token) {
    return (
      <main className="min-h-screen flex items-center justify-center p-6">
        <form onSubmit={(e) => { e.preventDefault(); sessionStorage.setItem("adminToken", input); setToken(input); }}
          className="w-full max-w-sm bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-4">
          <h1 className="text-lg font-bold">Admin</h1>
          <input type="password" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Admin token"
            className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-sm outline-none focus:border-orange-500" />
          {error && <p className="text-xs text-rose-400">{error}</p>}
          <button className="w-full bg-orange-600 hover:bg-orange-500 text-white font-bold py-3 rounded-lg text-sm">Open dashboard</button>
        </form>
      </main>
    );
  }
  if (!data) return <main className="p-8 text-sm text-zinc-400">{error || "Loading..."}</main>;

  const m = data.money, u = data.users, g = data.games;
  const recon = m.reconciliationDiffCents;
  return (
    <main className="max-w-6xl mx-auto p-4 md:p-8 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Admin dashboard</h1>
          <p className="text-[11px] text-zinc-500">Updated {data.generatedAt.replace("T", " ").slice(0, 19)} UTC {data.devMode && "· DEV MODE"}</p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="bg-zinc-900 border border-zinc-800 rounded-lg p-2">
            {[7, 14, 30, 60].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-zinc-400"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />Auto-refresh</label>
          <button onClick={load} className="bg-zinc-800 hover:bg-zinc-700 rounded-lg px-3 py-2">Refresh</button>
          <button onClick={() => { sessionStorage.removeItem("adminToken"); setToken(""); setData(null); }} className="text-zinc-500 hover:text-zinc-300">Log out</button>
        </div>
      </header>
      {error && <p className="text-xs text-rose-400">{error}</p>}

      {data.needsReview.length > 0 && (
        <section className="bg-amber-950/30 border border-amber-500/40 rounded-xl">
          <h2 className="p-4 pb-0 text-sm font-bold text-amber-300">Needs attention ({data.needsReview.length})</h2>
          <p className="px-4 text-[11px] text-amber-200/70">Payments stuck in review. Check each one with Safaricom before refunding or crediting.</p>
          <TxTable rows={data.needsReview} empty="" />
        </section>
      )}

      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Realized revenue" value={usd(m.realizedRevenueCents)} sub={`entry cut ${usd(m.depositCutCents)} + withdrawal fees ${usd(m.withdrawalFeesCents)}`} tone="good" />
        <Stat label="Owed to players now" value={usd(m.owedToPlayersCents)} sub="winnings + withdrawals in flight" tone="warn" />
        <Stat label="Prize pool" value={usd(m.poolBalanceCents)} sub={`funded ${usd(m.poolLifetimeFundedCents)} · paid ${usd(m.poolLifetimePaidCents)}`} />
        <Stat label="Deposits" value={usd(m.depositsCents)} sub={`${m.depositsCount} entry fees · KES ${Math.round((m.depositsCents / 100) * data.kesPerUsd)}`} />
        <Stat label="Paid out (withdrawals)" value={usd(m.withdrawalsGrossCents)} sub={`${m.withdrawalsCount} completed`} />
        <Stat label="Withdrawals in flight" value={usd(m.inFlightWithdrawalsCents)} tone={m.inFlightWithdrawalsCents ? "warn" : undefined} />
        <Stat label="Player balances (entry money)" value={usd(m.playerCollateralCents)} sub="not withdrawable" />
        <Stat label="Books check" value={recon === 0 ? "Balanced" : usd(recon)} tone={recon === 0 ? "good" : "bad"}
          sub={recon === 0 ? "cash in = held + paid out + our cut" : data.devMode ? "expected in dev (dev top-ups)" : "investigate: money doesn't add up"} />
      </section>

      <section className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <Stat label="Players" value={u.total} sub={`+${u.new7d} this week`} />
        <Stat label="Paid entry fee" value={u.paid} sub={u.total ? `${Math.round((100 * u.paid) / u.total)}% of signups` : ""} />
        <Stat label="Active (7 days)" value={u.active7d} />
        <Stat label="Finished practice" value={u.completedPractice} />
        <Stat label="Locked (balance $0)" value={u.locked} tone={u.locked ? "warn" : undefined} sub="may top up again" />
        <Stat label="Answer accuracy" value={`${g.accuracyPercent}%`} sub={`${g.finished} rounds finished`} />
      </section>

      <section className="grid md:grid-cols-2 gap-3">
        <Bars title="Signups per day" data={data.charts.signups} />
        <Bars title="Deposits per day" data={data.charts.depositsCents} money />
        <Bars title="Finished rounds per day" data={data.charts.rounds} />
        <Bars title="Withdrawals per day" data={data.charts.withdrawalsCents} money />
      </section>

      <section className="grid md:grid-cols-2 gap-3">
        <div className="bg-zinc-900/90 border border-zinc-800/80 rounded-xl p-4">
          <h2 className="text-sm font-bold mb-3">Categories</h2>
          <table className="w-full text-xs"><thead className="text-zinc-500 text-left"><tr><th className="py-1">Category</th><th>Rounds</th><th>Accuracy</th><th>Players net</th></tr></thead>
            <tbody>{data.categories.map((c) => (
              <tr key={c.category} className="border-t border-zinc-800/70"><td className="py-1.5 capitalize">{c.category === "custom" ? "surprise mix" : c.category}</td><td>{c.rounds}</td><td>{c.accuracyPercent}%</td>
                <td className={c.playersNetCents >= 0 ? "text-emerald-400" : "text-rose-400"}>{usd(c.playersNetCents)}</td></tr>))}</tbody></table>
          <p className="text-[11px] text-zinc-500 mt-2">{g.throttledRounds} paid rounds had a reduced payout because the pool was low.</p>
        </div>
        <div className="bg-zinc-900/90 border border-zinc-800/80 rounded-xl p-4">
          <h2 className="text-sm font-bold mb-3">Most active players</h2>
          <table className="w-full text-xs"><thead className="text-zinc-500 text-left"><tr><th className="py-1">Player</th><th>Rounds</th><th>Accuracy</th><th>Best streak</th><th>Can withdraw</th></tr></thead>
            <tbody>{data.topPlayers.map((p) => (
              <tr key={p.username} className="border-t border-zinc-800/70"><td className="py-1.5">{p.username}</td><td>{p.games}</td><td>{p.gamesAccuracyPercent}%</td><td>{p.bestStreak}</td><td>{usd(p.withdrawableCents)}</td></tr>))}</tbody></table>
        </div>
      </section>

      <section className="bg-zinc-900/90 border border-zinc-800/80 rounded-xl">
        <h2 className="text-sm font-bold p-4 pb-1">Recent transactions</h2>
        <TxTable rows={data.recentTransactions} empty="No transactions yet." />
      </section>
    </main>
  );
}