import { devLevel, poolAgeLevel, top10Level } from "./levels.js";

const DEXSCREENER_URL = "https://api.dexscreener.com/tokens/v1/solana/";
const GECKOTERMINAL_URL = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/";
const BROWSER_RPC_URL = "https://solana-rpc.publicnode.com";

export async function loadMarket(address, fetchImpl = fetch) {
  const response = await fetchImpl(DEXSCREENER_URL + encodeURIComponent(address));
  if (!response.ok) throw new Error(`DexScreener HTTP ${response.status}`);
  const pairs = await response.json();
  if (!Array.isArray(pairs) || pairs.length === 0) throw new Error("No pairs");
  const pair = pairs.reduce((best, current) =>
    (current.liquidity?.usd ?? 0) > (best.liquidity?.usd ?? 0) ? current : best
  );
  return {
    symbol: pair.baseToken?.symbol ?? null,
    name: pair.baseToken?.name ?? null,
    price_usd: pair.priceUsd ?? null,
    liquidity_usd: pair.liquidity?.usd ?? null,
    volume_24h: pair.volume?.h24 ?? null,
    ...(pair.pairCreatedAt
      ? {
          pool_created_at: new Date(pair.pairCreatedAt).toISOString(),
          pool_age_level: poolAgeLevel(pair.pairCreatedAt),
        }
      : {}),
  };
}

export async function loadAuthorities(address, fetchImpl = fetch) {
  const response = await fetchImpl(BROWSER_RPC_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "getAccountInfo",
      params: [address, { encoding: "jsonParsed" }],
    }),
  });
  if (!response.ok) throw new Error(`Solana RPC HTTP ${response.status}`);
  const parsed = (await response.json())?.result?.value?.data?.parsed;
  if (!parsed || parsed.type !== "mint") throw new Error("Not a token mint");
  return {
    authorities_loaded: true,
    mint_authority: parsed.info?.mintAuthority ?? null,
    freeze_authority: parsed.info?.freezeAuthority ?? null,
  };
}

export async function loadHolders(address, fetchImpl = fetch) {
  const response = await fetchImpl(`${GECKOTERMINAL_URL}${encodeURIComponent(address)}/info`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`GeckoTerminal HTTP ${response.status}`);
  const attributes = (await response.json())?.data?.attributes;
  const holders = attributes?.holders;
  const top10 = holders?.distribution_percentage?.top_10;
  if (top10 === undefined || top10 === null) throw new Error("No holders data");
  const dev = attributes?.developer_holding_percentage;
  return {
    holders_count: holders.count ?? null,
    top10_holders_pct: top10,
    top10_level: top10Level(Number(top10)),
    ...(dev !== undefined && dev !== null ? { developer_holding_pct: dev, dev_level: devLevel(Number(dev)) } : {}),
  };
}

function withoutErrors(errors, prefixes) {
  return errors.filter((error) => !prefixes.some((prefix) => error.startsWith(prefix)));
}

const SKIP = Promise.reject(new Error("skip"));
SKIP.catch(() => {});

export async function fillMissingData(report, fetchImpl = fetch) {
  const [market, authorities, holders] = await Promise.allSettled([
    report.market_source ? SKIP : loadMarket(report.address, fetchImpl),
    report.authorities_loaded ? SKIP : loadAuthorities(report.address, fetchImpl),
    report.top10_holders_pct !== null ? SKIP : loadHolders(report.address, fetchImpl),
  ]);
  let filled = report;
  if (market.status === "fulfilled") {
    filled = {
      ...filled,
      ...market.value,
      market_source: "DexScreener (direct)",
      errors: withoutErrors(filled.errors, ["DexScreener:", "GeckoTerminal:"]),
    };
  }
  if (authorities.status === "fulfilled") {
    filled = { ...filled, ...authorities.value, errors: withoutErrors(filled.errors, ["Solana RPC:"]) };
  }
  if (holders.status === "fulfilled") {
    filled = { ...filled, ...holders.value, errors: withoutErrors(filled.errors, ["Holders:"]) };
  }
  return filled;
}
