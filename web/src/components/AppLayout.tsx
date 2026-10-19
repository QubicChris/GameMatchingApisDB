import { useState, type KeyboardEvent } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  ActionIcon, AppShell, Avatar, Burger, Button, Group, Menu, NavLink, Text, TextInput,
  useComputedColorScheme, useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconAbc, IconBallFootball, IconFileSpreadsheet, IconLayoutDashboard, IconListDetails, IconLogout,
  IconMoon, IconRefresh, IconSearch, IconSun, IconTrendingDown, IconWorld,
} from '@tabler/icons-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthProvider';

const NAV = [
  { label: 'Overview', to: '/', icon: IconLayoutDashboard },
  { label: 'Games', to: '/games', icon: IconBallFootball },
  { label: 'Blown Leads', to: '/blown-leads', icon: IconTrendingDown },
  { label: 'Match Rates', to: '/match-rates', icon: IconWorld },
  { label: 'Team Aliases', to: '/aliases', icon: IconAbc },
  { label: 'Market Types', to: '/market-types', icon: IconListDetails },
  { label: 'Export', to: '/export', icon: IconFileSpreadsheet },
];

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? '?').toUpperCase() + (parts.length > 1 ? parts[parts.length - 1][0].toUpperCase() : '');
}

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user, logout } = useAuth();
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme('dark');
  const [search, setSearch] = useState('');
  const summary = useQuery({ queryKey: ['summary'], queryFn: api.summary });

  const isActive = (to: string) => location.pathname === to || (to !== '/' && location.pathname.startsWith(to + '/'));

  const onSearchKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && search.trim().length >= 2) {
      navigate('/games?q=' + encodeURIComponent(search.trim()));
    }
  };

  const onLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Text component={Link} to="/" fw={700} size="lg" style={{ textDecoration: 'none', color: 'inherit' }}>
              ⚽ Pregames
            </Text>
          </Group>
          <TextInput
            visibleFrom="sm"
            w={360}
            leftSection={<IconSearch size={16} />}
            placeholder="Search teams or leagues…"
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            onKeyDown={onSearchKey}
          />
          <Group gap="xs" wrap="nowrap">
            <ActionIcon
              variant="default"
              size="lg"
              aria-label="Toggle color scheme"
              onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}
            >
              {scheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
            </ActionIcon>
            <Menu position="bottom-end" width={200}>
              <Menu.Target>
                <Avatar color="teal" radius="xl" style={{ cursor: 'pointer' }}>
                  {initials(user?.name ?? user?.username ?? '?')}
                </Avatar>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{user?.name}</Menu.Label>
                <Menu.Item leftSection={<IconLogout size={16} />} onClick={onLogout}>
                  Log out
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <AppShell.Section grow>
          {NAV.map(({ label, to, icon: Icon }) => (
            <NavLink
              key={to}
              component={Link}
              to={to}
              label={label}
              leftSection={<Icon size={18} stroke={1.6} />}
              active={isActive(to)}
              onClick={close}
            />
          ))}
        </AppShell.Section>
        <AppShell.Section mt="auto">
          <Text size="xs" c="dimmed" mb="xs">
            Data: {summary.data?.date_from ?? '—'} → {summary.data?.date_to ?? '—'}
          </Text>
          <Button
            variant="light"
            fullWidth
            leftSection={<IconRefresh size={16} />}
            onClick={() => queryClient.invalidateQueries()}
          >
            Refresh data
          </Button>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
