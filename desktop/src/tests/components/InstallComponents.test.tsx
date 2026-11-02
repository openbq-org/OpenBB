/// <reference types="vitest/globals" />
import { beforeAll, afterEach, expect, test, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { randomFillSync } from 'crypto';
import { clearMocks } from '@tauri-apps/api/mocks';
import { PythonVersionSelector, ExtensionSelector } from '../../components/InstallComponents';

// Mock components from @openbb/ui-pro
vi.mock('@openbb/ui-pro', () => ({
  Button: vi.fn(({ children, ...props }) => (
    <button {...props}>
      {children}
    </button>
  )),
  Tooltip: vi.fn(({ children }) => <>{children}</>),
}));

// Mock ReactMarkdown
vi.mock('react-markdown', () => ({
  default: vi.fn(({ children }) => <div>{children}</div>),
}));

// Mock the global fetch API
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock data for extensions
const mockExtensionsData = {
  providers: [
    { packageName: 'provider1', reprName: 'Provider One', description: 'Desc 1', category: 'provider', credentials: ['API_KEY'] },
    { packageName: 'provider2', reprName: 'Provider Two', description: 'Desc 2', category: 'provider' },
  ],
  routers: [
    { packageName: 'router1', reprName: 'Router One', description: 'Desc A', category: 'router' },
  ],
  obbjects: [
    { packageName: 'obbject1', reprName: 'OBBject One', description: 'Desc X', category: 'other-openbb' },
  ],
};

beforeAll(() => {
  Object.defineProperty(window, 'crypto', {
    value: {
      getRandomValues: (buffer: Uint8Array | Uint16Array | Uint32Array) => {
        return randomFillSync(buffer);
      },
    },
  });
});

// Clear mocks after each test to ensure test isolation
afterEach(() => {
  clearMocks();
  vi.clearAllMocks(); // Clear fetch mock calls
});

test('PythonVersionSelector renders and handles version selection', () => {
  const onSelectVersion = vi.fn();

  render(<PythonVersionSelector onSelectVersion={onSelectVersion} />);

  expect(onSelectVersion).toHaveBeenCalledWith('3.13');

  const python311Radio = screen.getByLabelText(/3.11/i);
  fireEvent.click(python311Radio);

  expect(onSelectVersion).toHaveBeenCalledWith('3.11');
  expect(python311Radio).toBeChecked();
});

test('ExtensionSelector displays loading state initially', () => {
  mockFetch.mockImplementation(() =>
    new Promise(() => {}) // Never resolve to keep it in loading state
  );
  render(<ExtensionSelector onInstallExtensions={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.getByText(/Loading extensions.../i)).toBeInTheDocument();
});

test('ExtensionSelector fetches and displays extensions', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  render(<ExtensionSelector onInstallExtensions={vi.fn()} onCancel={vi.fn()} />);

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('tab', { name: /Data Providers/i }));
  expect(screen.getByText(/provider1/i)).toBeInTheDocument();
});

test('ExtensionSelector handles search and selection', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  render(<ExtensionSelector onInstallExtensions={vi.fn()} onCancel={vi.fn()} />);

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('tab', { name: /Data Providers/i }));

  const searchInput = screen.getByPlaceholderText(/Search extensions.../i);
  fireEvent.change(searchInput, { target: { value: 'provider one' } });

  expect(screen.getByText(/provider1/i)).toBeInTheDocument();
  expect(screen.queryByText(/provider2/i)).not.toBeInTheDocument();

  fireEvent.change(searchInput, { target: { value: '' } });
  expect(screen.getByText(/provider2/i)).toBeInTheDocument();

  const provider1Checkbox = screen.getByLabelText(/provider1/i);
  const provider2Checkbox = screen.getByLabelText(/provider2/i);

  // Test selecting one
  fireEvent.click(provider1Checkbox);
  expect(provider1Checkbox).toBeChecked();
  expect(provider2Checkbox).not.toBeChecked();

  // Test select all
  fireEvent.click(screen.getByRole('button', { name: /Select all/i }));
  expect(provider1Checkbox).toBeChecked();
  expect(provider2Checkbox).toBeChecked();

  // Test deselect all by clicking the main checkbox
  const allCheckboxes = screen.getAllByRole('checkbox');
  const deselectAllCheckbox = allCheckboxes[0];
  fireEvent.click(deselectAllCheckbox);

  expect(provider1Checkbox).not.toBeChecked();
  expect(provider2Checkbox).not.toBeChecked();
});

test('ExtensionSelector calls onInstallExtensions with correct data', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  const onInstallExtensions = vi.fn();
  render(<ExtensionSelector onInstallExtensions={onInstallExtensions} onCancel={vi.fn()} />);

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  // Add a conda package
  fireEvent.click(screen.getByRole('tab', { name: /Conda Packages/i }));
  const condaPackageInput = screen.getByPlaceholderText(/Conda Package Name/i);
  fireEvent.change(condaPackageInput, { target: { value: 'my-conda-package' } });
  fireEvent.click(screen.getByRole('button', { name: /Add/i }));

  // Add a pypi package
  fireEvent.click(screen.getByRole('tab', { name: /PyPI Packages/i }));
  const pypiPackageInput = screen.getByPlaceholderText(/PyPI Package Name/i);
  fireEvent.change(pypiPackageInput, { target: { value: 'my-pypi-package' } });
  fireEvent.click(screen.getByRole('button', { name: /Add/i }));

  // Select a provider
  fireEvent.click(screen.getByRole('tab', { name: /Data Providers/i }));
  fireEvent.click(screen.getByLabelText(/provider1/i));

  fireEvent.click(screen.getByRole('button', { name: /Create Environment/i }));

  expect(onInstallExtensions).toHaveBeenCalledWith([
    'provider1',
    'my-pypi-package',
    'conda:conda-forge:my-conda-package',
  ]);
});
