import "@ant-design/v5-patch-for-react-19";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import type { Metadata } from "next";
import Script from "next/script";
import { Providers } from "@/components/Providers";
import "./globals.css";

const themeBoot = `try{var t=localStorage.getItem("paleonia.theme");if(t!=="light"&&t!=="dark")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=t}catch(e){}`;

export const metadata: Metadata = {
  title: "PaleonIA",
  description: "Mesa de transcrição de manuscritos",
  icons: { icon: "/brand/PaleonIA-logo.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body>
        <Script id="paleonia-theme" strategy="beforeInteractive">
          {themeBoot}
        </Script>
        <AntdRegistry>
          <Providers>{children}</Providers>
        </AntdRegistry>
      </body>
    </html>
  );
}
