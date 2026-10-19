import { useState, type FormEvent } from 'react';
import { Alert, Button, Center, Group, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconAlertCircle } from '@tabler/icons-react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from './AuthProvider';

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const from = (location.state as { from?: string } | null)?.from ?? '/';

  if (user) return <Navigate to={from} replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Center h="100vh">
      <Paper withBorder shadow="md" p="xl" w={380} maw="92vw">
        <form onSubmit={onSubmit}>
          <Stack gap="md">
            <div>
              <Group gap="xs">
                <Text fz={28}>⚽</Text>
                <Title order={2}>Pregames</Title>
              </Group>
              <Text c="dimmed" size="sm">Sign in to the data browser</Text>
            </div>
            {error && (
              <Alert color="red" icon={<IconAlertCircle />}>
                {error}
              </Alert>
            )}
            <TextInput
              label="Username"
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.currentTarget.value)}
              required
            />
            <PasswordInput
              label="Password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              required
            />
            <Button type="submit" fullWidth loading={submitting}>
              Sign in
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
