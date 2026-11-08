// Every sentence the dashboard says is in src/strings/en.json. Bundled, so nothing is fetched.
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./strings/en.json";

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: "en",
  fallbackLng: "en",
  initAsync: false,
  interpolation: { escapeValue: false }, // React escapes text itself
  returnNull: false,
});

export default i18n;
