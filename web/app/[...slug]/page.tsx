import { ScreenRouter } from "@/components/Screens";

type PageProps = {
  params: Promise<{ slug: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function CatchAllPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const resolvedSearchParams = await searchParams;
  return <ScreenRouter path={`/${slug.join("/")}`} searchParams={resolvedSearchParams} />;
}

