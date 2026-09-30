import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Quick IQ - Cyber Gaming Arena",
  description: "Real-time trivia platform with live M-Pesa settlement",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-100 min-h-screen antialiased selection:bg-cyan-500 selection:text-slate-950">
        {children}
      </body>
    </html>
  );
}