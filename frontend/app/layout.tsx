import "./globals.css";
import type { Metadata, Viewport } from "next";
import { Sora, Plus_Jakarta_Sans } from "next/font/google";

const display = Sora({ subsets: ["latin"], variable: "--font-display", weight: ["600", "700", "800"] });
const body = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-body" });

export const metadata: Metadata = {
  title: "Quick Train - Timed Trivia & Real Reward ",
  description: "Fast timed trivia. Activate and withdraw with M-Pesa.",
};

export const viewport: Viewport = { themeColor: "#0b1020" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // data-theme: "coral" | "violet" | "ocean"
    <html lang="en" className={`dark ${display.variable} ${body.variable}`} data-theme="coral">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}