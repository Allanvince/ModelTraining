"use client";

import { useEffect, useState } from "react";

export interface LeaderboardEntry {
  rank: number;
  username: string;
  score: number;
  streak: number;
}

export function useLeaderboard() {
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const baseUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");
    const wsUrl = baseUrl.replace(/^http/, "ws") + "/ws/leaderboard";
    
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "leaderboard") {
          setLeaderboard(data.top);
        }
      } catch (err) {
        console.error("WS Parse Error:", err);
      }
    };

    return () => ws.close();
  }, []);

  return { leaderboard, connected };
}