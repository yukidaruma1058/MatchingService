/** スキル文から技術名と工程を切り出す（採点・ハイライト用）。 */

export const PHASE_ORDER = [
  "要件定義",
  "基本設計",
  "詳細設計",
  "製造",
  "単体試験",
  "結合試験",
  "システム試験",
  "リリース",
] as const;

const PHASE_ALIASES: [string, string][] = [
  ["リリース作業", "リリース"],
  ["本番リリース", "リリース"],
  ["システムテスト", "システム試験"],
  ["システム試験", "システム試験"],
  ["総合テスト", "システム試験"],
  ["総合試験", "システム試験"],
  ["結合テスト", "結合試験"],
  ["結合試験", "結合試験"],
  ["単体テスト", "単体試験"],
  ["単体試験", "単体試験"],
  ["プログラミング", "製造"],
  ["コーディング", "製造"],
  ["外部設計", "基本設計"],
  ["内部設計", "詳細設計"],
  ["要件定義", "要件定義"],
  ["基本設計", "基本設計"],
  ["詳細設計", "詳細設計"],
  ["実装", "製造"],
  ["製造", "製造"],
  ["本番", "リリース"],
  ["リリース", "リリース"],
];

const TECH_CANONICAL = [
  "TypeScript",
  "JavaScript",
  "PostgreSQL",
  "SQL Server",
  "Spring Boot",
  "Objective-C",
  "Kubernetes",
  "Terraform",
  "MongoDB",
  "Next.js",
  "Vue.js",
  "Node.js",
  "Angular",
  "Oracle",
  "MySQL",
  "Redis",
  "Docker",
  "Linux",
  "Azure",
  "Kotlin",
  "Python",
  "React",
  "Spring",
  "Ansible",
  "Java",
  "AWS",
  "GCP",
  "PHP",
  "Ruby",
  "Scala",
  "Swift",
  "HTML",
  "CSS",
  "Git",
  "C#",
  "Go",
];

const ONWARD = /^(?:以降|以上|以後)/;

function nfc(text: string): string {
  return text.normalize("NFKC").trim();
}

function findPhaseSpans(text: string): { start: number; end: number; canonical: string }[] {
  const occupied: [number, number][] = [];
  const spans: { start: number; end: number; canonical: string }[] = [];
  const aliases = [...PHASE_ALIASES].sort((a, b) => b[0].length - a[0].length);
  for (const [alias, canonical] of aliases) {
    let from = 0;
    while (from < text.length) {
      const idx = text.indexOf(alias, from);
      if (idx < 0) {
        break;
      }
      const end = idx + alias.length;
      if (occupied.some(([left, right]) => !(end <= left || idx >= right))) {
        from = idx + 1;
        continue;
      }
      spans.push({ start: idx, end, canonical });
      occupied.push([idx, end]);
      from = end;
    }
  }
  return spans.sort((a, b) => a.start - b.start);
}

function extractTechNames(text: string): string[] {
  const found: string[] = [];
  const seen = new Set<string>();
  for (const name of TECH_CANONICAL) {
    let matched = false;
    if (name === "Go") {
      matched = /(?<![A-Za-z0-9])Go(?:言語)?(?![A-Za-z0-9])/.test(text);
    } else if (name === "C#") {
      matched = /(?<![A-Za-z0-9])C#(?![A-Za-z0-9])/i.test(text);
    } else if (/^[A-Za-z0-9.+#\- ]+$/.test(name)) {
      const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\ /g, "[\\s　]*");
      matched = new RegExp(`(?<![A-Za-z0-9])${escaped}(?![A-Za-z0-9])`, "i").test(text);
    } else {
      matched = text.toLowerCase().includes(name.toLowerCase());
    }
    if (matched && !seen.has(name)) {
      seen.add(name);
      found.push(name);
    }
  }
  return found;
}

export function expandSkillTerm(raw: string): string[] {
  const text = nfc(raw);
  if (!text) {
    return [];
  }
  const spans = findPhaseSpans(text);
  let phases: string[] = [];
  let onwardFrom: string | null = null;
  for (const span of spans) {
    const rest = text.slice(span.end).replace(/^[ 　・,、/｜|]+/, "");
    if (ONWARD.test(rest)) {
      onwardFrom = span.canonical;
      break;
    }
  }
  if (onwardFrom) {
    const index = PHASE_ORDER.indexOf(onwardFrom as (typeof PHASE_ORDER)[number]);
    phases = index >= 0 ? [...PHASE_ORDER.slice(index)] : [onwardFrom];
  } else {
    const seen = new Set<string>();
    for (const span of spans) {
      if (!seen.has(span.canonical)) {
        seen.add(span.canonical);
        phases.push(span.canonical);
      }
    }
  }
  const techs = extractTechNames(text);
  const combined = [...techs, ...phases.filter((phase) => !techs.includes(phase))];
  if (combined.length > 0) {
    return combined;
  }
  return [raw.trim()].filter(Boolean);
}

export function expandSkillItems(values: string[] | undefined | null): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of values ?? []) {
    for (const item of expandSkillTerm(String(value))) {
      const key = nfc(item).toLowerCase();
      if (!key || seen.has(key)) {
        continue;
      }
      seen.add(key);
      result.push(item);
    }
  }
  return result;
}

export function skillsMatch(talentSkill: string, requiredSkill: string): boolean {
  const talentTerms = expandSkillTerm(talentSkill).map((item) => nfc(item).toLowerCase());
  const requiredTerms = expandSkillTerm(requiredSkill).map((item) => nfc(item).toLowerCase());
  return requiredTerms.some((req) => talentTerms.some((have) => have === req || have.includes(req) || req.includes(have)));
}
