"use client";

import "@ant-design/v5-patch-for-react-19";
import { App, ConfigProvider } from "antd";
import { deskTheme } from "./theme";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ConfigProvider theme={deskTheme}>
      <App>{children}</App>
    </ConfigProvider>
  );
}
