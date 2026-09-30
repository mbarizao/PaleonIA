import type { ThemeConfig } from "antd";
import { theme } from "antd";

export type ThemeMode = "light" | "dark";

const shared = {
  borderRadius: 6,
  fontFamily: '"Segoe UI", system-ui, sans-serif',
  fontSize: 14,
  controlHeight: 34,
};

export function deskTheme(mode: ThemeMode): ThemeConfig {
  const dark = mode === "dark";
  return {
    algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: dark ? "#e6edf4" : "#0a253e",
      colorInfo: dark ? "#d4a45a" : "#0a253e",
      colorLink: dark ? "#d4a45a" : "#0a253e",
      colorTextLightSolid: dark ? "#10161d" : "#ffffff",
      colorBgLayout: dark ? "#10161d" : "#f3f5f8",
      colorBgContainer: dark ? "#1a222c" : "#ffffff",
      colorBgElevated: dark ? "#222b36" : "#ffffff",
      colorText: dark ? "#e6edf4" : "#12263a",
      colorTextSecondary: dark ? "#b7c3d0" : "#5c6e80",
      colorTextTertiary: dark ? "#93a3b3" : "#7d8b99",
      colorBorder: dark ? "#2c3948" : "#e1e7ee",
      colorBorderSecondary: dark ? "#243140" : "#eef1f5",
      ...shared,
    },
    components: {
      Layout: {
        headerBg: "#0a253e",
        headerHeight: 56,
        headerPadding: "0 20px",
        headerColor: "#f4f7fb",
        siderBg: dark ? "#1a222c" : "#ffffff",
        bodyBg: dark ? "#10161d" : "#f3f5f8",
        lightSiderBg: dark ? "#1a222c" : "#ffffff",
      },
      Button: {
        primaryShadow: "none",
        defaultShadow: "none",
        fontWeight: 600,
      },
      Menu: {
        itemSelectedBg: dark ? "#243140" : "#f4f7fb",
        itemSelectedColor: dark ? "#f3f6fa" : "#0a253e",
      },
      Modal: {
        titleFontSize: 16,
      },
    },
  };
}
