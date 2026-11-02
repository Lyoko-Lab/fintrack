// Plaid Link, loaded from Plaid's CDN on first use. Bank credentials are typed into
// Plaid's own window; Fintrack only ever receives a one-time public token.
import { api } from "./api";
import { messages } from "./i18n";

interface PlaidHandler {
  open(): void;
  destroy(): void;
}

interface PlaidLinkConfig {
  token: string;
  onSuccess(publicToken: string, metadata: { institution: { institution_id: string; name: string } | null }): void;
  onExit(error: { error_code: string; error_message: string; display_message: string | null } | null): void;
}

declare global {
  interface Window {
    Plaid?: { create(config: PlaidLinkConfig): PlaidHandler };
  }
}

const SCRIPT_URL = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";
let scriptLoad: Promise<void> | null = null;

function loadScript(): Promise<void> {
  scriptLoad ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptLoad = null;
      reject(new Error(messages().errors.plaidScript));
    };
    document.head.append(script);
  });
  return scriptLoad;
}

/**
 * Connect a new bank, or with `itemId` repair an existing connection in update mode.
 * Resolves true once the server has the connection, false if the user closed Link.
 */
export async function openPlaidLink(itemId?: number): Promise<boolean> {
  const [{ link_token }] = await Promise.all([api.linkToken(itemId), loadScript()]);
  return new Promise((resolve, reject) => {
    const handler = window.Plaid!.create({
      token: link_token,
      onSuccess: (publicToken, metadata) => {
        const saved =
          itemId === undefined
            ? api.exchange(publicToken, metadata.institution?.institution_id ?? null, metadata.institution?.name ?? null)
            : api.reconnected(itemId);
        saved.then(() => resolve(true), reject).finally(() => handler.destroy());
      },
      onExit: (error) => {
        handler.destroy();
        if (error) reject(new Error(error.display_message || error.error_message || error.error_code));
        else resolve(false);
      },
    });
    handler.open();
  });
}
