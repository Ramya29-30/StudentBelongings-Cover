import { deflateSync } from 'node:zlib';
import { expect, type Page } from '@playwright/test';

export const USERS = {
  riya: { username: 'riya', password: 'student123', home: /\/student$/, heading: /Welcome, Riya/ },
  admin: { username: 'admin', password: 'admin123', home: /\/admin$/, heading: /Overview/ },
  assessor: { username: 'assessor', password: 'assessor123', home: /\/assessor$/, heading: /Assessor dashboard/ },
} as const;

export function watchBrowser(page: Page) {
  const problems: string[] = [];
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() !== 'error' && m.type() !== 'warning') return;
    const t = m.text();
    if (/Failed to load resource: the server responded with a status of 4\d\d/.test(t)) return;
    problems.push(`console.${m.type()}: ${t}`);
  });
  return { problems, assertClean: () => expect(problems, 'browser console / CSP / page errors').toEqual([]) };
}

export async function loginAs(page: Page, who: keyof typeof USERS) {
  const u = USERS[who];
  await page.goto('/login');
  await page.getByLabel('Username').fill(u.username);
  await page.getByLabel('Password').fill(u.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(u.home);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(u.heading);
}

/** A sharp noisy PNG (passes the server's blur, darkness and size checks). Built with Node's zlib only. */
export function makePng(seed = 1, w = 640, h = 480): Buffer {
  const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (b: Buffer) => { let c = 0xffffffff; for (const x of b) c = crcTable[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (t: string, d: Buffer) => { const len = Buffer.alloc(4); len.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([len, td, c]); };
  let s = seed >>> 0 || 1;
  const rnd = () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s; };
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) { raw[y * (w * 3 + 1)] = 0; for (let i = 0; i < w * 3; i++) raw[y * (w * 3 + 1) + 1 + i] = 60 + (rnd() % 140); }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
