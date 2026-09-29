import type { ThemeConfig } from "antd";
import { theme } from "antd";

export const deskTheme: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#0a253e",
    colorInfo: "#0a253e",
    colorLink: "#0a253e",
    colorTextLightSolid: "#ffffff",
    colorBgLayout: "#f3f5f8",
    colorBgContainer: "#ffffff",
    colorBgElevated: "#ffffff",
    colorText: "#12263a",
    colorTextSecondary: "#5c6e80",
    colorTextTertiary: "#7d8b99",
    colorBorder: "#e1e7ee",
    colorBorderSecondary: "#eef1f5",
    borderRadius: 6,
    fontFamily: '"Segoe UI", system-ui, sans-serif',
    fontSize: 14,
    controlHeight: 34,
  },
  components: {
    Layout: {
      headerBg: "#0a253e",
      headerHeight: 56,
      headerPadding: "0 20px",
      headerColor: "#f4f7fb",
      siderBg: "#ffffff",
      bodyBg: "#f3f5f8",
      lightSiderBg: "#ffffff",
    },
    Button: {
      primaryShadow: "none",
      defaultShadow: "none",
      fontWeight: 600,
    },
    Menu: {
      itemSelectedBg: "#f4f7fb",
      itemSelectedColor: "#0a253e",
    },
    Modal: {
      titleFontSize: 16,
    },
  },
};
