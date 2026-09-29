export type Part = {
  id: string;
  text: string;
  parte?: number;
  linha_transcrita?: number | null;
};

export type Line = {
  id: string;
  box: number[];
  include: boolean;
  linha_documento?: number;
  parts: Part[];
};

export type Page = {
  id: string;
  filename: string;
  width: number;
  height: number;
  original_width: number;
  original_height: number;
  crop_origin: number[];
  prepared?: boolean;
  sensitivity: number;
  image_url: string;
  original_url: string;
  lines: Line[];
};

export type Session = {
  app_name: string;
  default_sensitivity: number;
  reader: string;
  work_dir: string;
  pages: Page[];
};

export type AuthState = {
  required: boolean;
  authenticated: boolean;
  username: string;
};

export type TranscribeJob = {
  status: string;
  message: string;
  done: number;
  total: number;
  page: Page | null;
};
