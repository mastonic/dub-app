import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Doublage FR",
  description: "Traduis une vidéo X ou YouTube en français oral.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
