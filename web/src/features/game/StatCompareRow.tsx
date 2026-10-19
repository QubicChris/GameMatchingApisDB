import { Group, Progress, Text } from '@mantine/core';
import { formatStat, homeShare, type StatKind } from './statGroups';

interface StatCompareRowProps {
  label: string;
  kind: StatKind;
  home: number;
  away: number;
  homeTotal: number | null;
  awayTotal: number | null;
}

export function StatCompareRow({ label, kind, home, away, homeTotal, awayTotal }: StatCompareRowProps) {
  const share = homeShare(home, away);
  return (
    <div style={{ marginBottom: 10 }}>
      <Group justify="space-between" wrap="nowrap" gap="xs">
        <Text fw={600} size="sm" className="num">{formatStat(kind, home, homeTotal)}</Text>
        <Text size="xs" c="dimmed" ta="center">{label}</Text>
        <Text fw={600} size="sm" className="num">{formatStat(kind, away, awayTotal)}</Text>
      </Group>
      <Progress.Root size="sm" mt={4}>
        <Progress.Section value={share} color="teal" />
        <Progress.Section value={100 - share} color="orange" />
      </Progress.Root>
    </div>
  );
}
