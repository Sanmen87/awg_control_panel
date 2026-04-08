import "./globals.css";
import "./mobile.css";
import type { Metadata } from "next";
import { AuthProvider } from "../components/auth-context";
import { LocaleProvider } from "../components/locale-context";

export const metadata: Metadata = {
  title: "AWG Control Panel",
  description: "VPN infrastructure control plane for AWG proxy and failover topologies."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <LocaleProvider>
          <AuthProvider>{children}</AuthProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
