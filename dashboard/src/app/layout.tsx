import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARES Dashboard",
  description: "Overview, kesehatan sistem, dan watchlist untuk bot ARES.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="id">
      <body>{children}</body>
    </html>
  );
}
