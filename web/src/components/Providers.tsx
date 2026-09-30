"use client";

import "@ant-design/v5-patch-for-react-19";
import { App, ConfigProvider } from "antd";
import { deskTheme } from "./theme";
import { useThemeMode } from "./theme-mode";

export function Providers({ children }: { children: React.ReactNode }) {
  const mode = useThemeMode();
  return (
    <ConfigProvider theme={deskTheme(mode)}>
      <App>{children}</App>
    </ConfigProvider>
  );
}
