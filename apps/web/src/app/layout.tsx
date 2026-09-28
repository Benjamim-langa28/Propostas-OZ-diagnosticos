import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OZ Propostas | Diagnóstico e Engenharia",
  description: "Gestão de pedidos, diagnósticos e propostas técnicas OZ.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt">
      <body>{children}</body>
    </html>
  );
}
