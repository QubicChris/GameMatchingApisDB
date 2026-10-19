import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Badge, Group, Paper, SimpleGrid, Switch, Table, Text, TextInput } from '@mantine/core';
import { IconFilter } from '@tabler/icons-react';
import { api } from '../../api/client';
import type { GameDetail } from '../../api/types';
import { QueryState } from '../../components/QueryState';
import { DASH, bestBookmakers, formatOdd } from '../../lib/format';

export function OddsTab({ game }: { game: GameDetail }) {
  const odds = useQuery({ queryKey: ['odds', game.id], queryFn: () => api.odds(game.id) });
  const [filter, setFilter] = useState('');
  const [onlySofa, setOnlySofa] = useState(false);

  const markets = useMemo(() => {
    const all = odds.data?.markets ?? [];
    const f = filter.trim().toLowerCase();
    return all.filter(
      (m) =>
        (!f || m.name.toLowerCase().includes(f)) &&
        (!onlySofa || m.rows.some((r) => r.sofa_close != null)),
    );
  }, [odds.data, filter, onlySofa]);

  const bookmakers = odds.data?.bookmakers ?? [];

  return (
    <QueryState query={odds} empty={(odds.data?.markets.length ?? 0) === 0} emptyText="No odds data for this game.">
      <Group mb="md" gap="md">
        <TextInput
          placeholder="Filter markets…" leftSection={<IconFilter size={14} />}
          value={filter} onChange={(e) => setFilter(e.currentTarget.value)}
        />
        <Switch
          label="Only markets with Sofa closing odds"
          checked={onlySofa} onChange={(e) => setOnlySofa(e.currentTarget.checked)}
        />
      </Group>
      {markets.length === 0 ? (
        <Text c="dimmed" ta="center" py="xl">No markets match the filters.</Text>
      ) : (
        <SimpleGrid cols={{ base: 1, xl: 2 }}>
          {markets.map((m) => (
            <Paper key={m.umid} withBorder p="md">
              <Group justify="space-between" mb="xs">
                <Text fw={600}>{m.name}</Text>
                <Badge size="xs" variant="default">#{m.umid}</Badge>
              </Group>
              <Table.ScrollContainer minWidth={300}>
                <Table verticalSpacing={4}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Outcome</Table.Th>
                      {bookmakers.map((b) => (
                        <Table.Th key={b} ta="right">{b}</Table.Th>
                      ))}
                      <Table.Th ta="right">Sofa close</Table.Th>
                      <Table.Th ta="center">Result</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {m.rows.map((r, idx) => {
                      const priced = Object.values(r.odds).filter((v) => v != null).length;
                      const best = priced >= 2 ? new Set(bestBookmakers(r.odds)) : new Set<string>();
                      return (
                        <Table.Tr key={`${r.outcome}-${r.line_value}-${idx}`}>
                          <Table.Td>{r.label}</Table.Td>
                          {bookmakers.map((b) => (
                            <Table.Td
                              key={b} ta="right" className="num"
                              fw={best.has(b) ? 700 : undefined} c={best.has(b) ? 'teal' : undefined}
                            >
                              {formatOdd(r.odds[b])}
                            </Table.Td>
                          ))}
                          <Table.Td ta="right" className="num">{formatOdd(r.sofa_close)}</Table.Td>
                          <Table.Td ta="center">
                            {r.sofa_winning === 1 ? (
                              <Badge color="teal">Won</Badge>
                            ) : r.sofa_winning === 0 ? (
                              <Badge color="gray" variant="light">Lost</Badge>
                            ) : (
                              DASH
                            )}
                          </Table.Td>
                        </Table.Tr>
                      );
                    })}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            </Paper>
          ))}
        </SimpleGrid>
      )}
      <Text size="xs" c="dimmed" mt="md">
        Best price per outcome highlighted. Sofa close = Bet365 closing odds via Sofasport.
      </Text>
    </QueryState>
  );
}
