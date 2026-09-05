import type { ReactNode } from "react";
import "./styles.css";

export const metadata = {
  title: "Artist Growth OS",
  description: "Rights-aware multi-artist creative operating system",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
