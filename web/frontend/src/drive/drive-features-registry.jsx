import React from 'react'

// ============================================================
//  DRIVE FEATURES REGISTRY
//  Catalog of ~100 feature panels organized by category.
//  Uses runtime dynamic import with fallback for missing panels.
// ============================================================

/**
 * Placeholder component shown when a panel file doesn't exist yet.
 */
function ComingSoonPanel({ name }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '100%', minHeight: 300,
      color: '#888', gap: '0.75rem',
    }}>
      <span style={{ fontSize: '2.5rem' }}>&#x1F6A7;</span>
      <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>
        {name || 'Feature'} &mdash; Coming Soon
      </span>
      <span style={{ fontSize: '0.75rem', color: '#555' }}>
        This panel is under development
      </span>
    </div>
  )
}

/**
 * Create a lazy component that loads a panel by path.
 * Falls back to ComingSoonPanel if the module doesn't exist.
 * Uses @vite-ignore so Vite won't fail at build time.
 */
export function createLazyPanel(panelPath, featureName) {
  return React.lazy(() =>
    import(/* @vite-ignore */ panelPath).catch(() => ({
      default: () => <ComingSoonPanel name={featureName} />,
    }))
  )
}

// ============================================================
//  CATEGORIES
// ============================================================

export const CATEGORIES = [
  { id: 'files',    icon: '\uD83D\uDCC1', label: 'Files & Organization' },
  { id: 'sharing',  icon: '\uD83E\uDD1D', label: 'Sharing & Collaboration' },
  { id: 'sync',     icon: '\uD83D\uDD04', label: 'Sync & Devices' },
  { id: 'backup',   icon: '\uD83D\uDD10', label: 'Backup & Recovery' },
  { id: 'account',  icon: '\uD83D\uDC64', label: 'Account & Security' },
  { id: 'settings', icon: '\u2699\uFE0F', label: 'Settings & Preferences' },
  { id: 'help',     icon: '\uD83D\uDEA8', label: 'Help & Troubleshooting' },
]

// ============================================================
//  FEATURES (~100 entries)
//  Each entry has: id, name, icon, category, panelPath
//  The lazy component is created on-demand when a feature is opened.
// ============================================================

export const FEATURES = [
  // -- Files & Organization --
  { id: 'gallery-view',      name: 'Gallery View',       icon: '\uD83D\uDDBC\uFE0F', category: 'files',    panelPath: './panels/GalleryViewPanel'       },
  { id: 'camera-uploads',    name: 'Camera Uploads',     icon: '\uD83D\uDCF7',       category: 'files',    panelPath: './panels/CameraUploadsPanel'     },
  { id: 'copy-files',        name: 'Copy Files',         icon: '\uD83D\uDCCB',       category: 'files',    panelPath: './panels/CopyFilesPanel'         },
  { id: 'move-files',        name: 'Move Files',         icon: '\uD83D\uDCE6',       category: 'files',    panelPath: './panels/MoveFilesPanel'         },
  { id: 'multi-select',      name: 'Multi-Select',       icon: '\u2611\uFE0F',       category: 'files',    panelPath: './panels/MultiSelectPanel'       },
  { id: 'hidden-files',      name: 'Hidden Files',       icon: '\uD83D\uDC41\uFE0F', category: 'files',    panelPath: './panels/HiddenFilesPanel'       },
  { id: 'file-dates',        name: 'File Dates',         icon: '\uD83D\uDCC5',       category: 'files',    panelPath: './panels/FileDatesPanel'         },
  { id: 'add-content',       name: 'Add Content',        icon: '\u2795',             category: 'files',    panelPath: './panels/AddContentPanel'        },
  { id: 'video-playlist',    name: 'Video Playlists',    icon: '\uD83C\uDFAC',       category: 'files',    panelPath: './panels/VideoPlaylistPanel'     },
  { id: 'files-advanced',    name: 'Files Advanced',     icon: '\uD83D\uDCC2',       category: 'files',    panelPath: './panels/FilesAdvancedPanel'     },
  { id: 'navigation',        name: 'Navigation',         icon: '\uD83E\uDDED',       category: 'files',    panelPath: './panels/NavigationPanel'        },
  { id: 'content-mgmt',      name: 'Content Management', icon: '\uD83D\uDCDA',       category: 'files',    panelPath: './panels/ContentMgmtPanel'      },
  { id: 'view-move',         name: 'View & Move',        icon: '\uD83D\uDD0D',       category: 'files',    panelPath: './panels/ViewMovePanel'          },
  { id: 'albums-overview',   name: 'Albums Overview',    icon: '\uD83D\uDCF8',       category: 'files',    panelPath: './panels/AlbumsOverviewPanel'    },

  // -- Sharing & Collaboration --
  { id: 'shared-items',      name: 'Shared Items',       icon: '\uD83D\uDD17',       category: 'sharing',  panelPath: './panels/SharedItemsPanel'       },
  { id: 'shared-folders',    name: 'Shared Folders',     icon: '\uD83D\uDCC2',       category: 'sharing',  panelPath: './panels/SharedFoldersPanel'     },
  { id: 'sharing-link',      name: 'Sharing Links',      icon: '\uD83D\uDD17',       category: 'sharing',  panelPath: './panels/SharingLinkPanel'       },
  { id: 'share-overview',    name: 'Share Overview',     icon: '\uD83D\uDCCA',       category: 'sharing',  panelPath: './panels/ShareOverviewPanel'     },
  { id: 'secure-sharing',    name: 'Secure Sharing',     icon: '\uD83D\uDD12',       category: 'sharing',  panelPath: './panels/SecureSharingPanel'     },
  { id: 'collaboration',     name: 'Collaboration',      icon: '\uD83D\uDC65',       category: 'sharing',  panelPath: './panels/CollaborationPanel'     },
  { id: 'collab-tools',      name: 'Collab Tools',       icon: '\uD83D\uDEE0\uFE0F', category: 'sharing',  panelPath: './panels/CollabToolsPanel'       },
  { id: 'team-collab',       name: 'Team Collaboration', icon: '\uD83D\uDC6B',       category: 'sharing',  panelPath: './panels/TeamCollabPanel'        },
  { id: 'smart-workspace',   name: 'Smart Workspace',    icon: '\uD83D\uDCA1',       category: 'sharing',  panelPath: './panels/SmartWorkspacePanel'    },
  { id: 'project-hub',       name: 'Project Hub',        icon: '\uD83C\uDFAF',       category: 'sharing',  panelPath: './panels/ProjectHubPanel'        },
  { id: 'workspace-activity', name: 'Workspace Activity', icon: '\uD83D\uDCCA',      category: 'sharing',  panelPath: './panels/WorkspaceActivityPanel' },
  { id: 'relay-workflow',    name: 'Relay Workflow',     icon: '\uD83D\uDD04',       category: 'sharing',  panelPath: './panels/RelayWorkflowPanel'     },

  // -- Sync & Devices --
  { id: 'sync-status',       name: 'Sync Status',        icon: '\uD83D\uDD04',       category: 'sync',     panelPath: './panels/SyncStatusPanel'        },
  { id: 'sync-health',       name: 'Sync Health',        icon: '\uD83D\uDC9A',       category: 'sync',     panelPath: './panels/SyncHealthPanel'        },
  { id: 'sync-rule',         name: 'Sync Rules',         icon: '\uD83D\uDCCB',       category: 'sync',     panelPath: './panels/SyncRulePanel'          },
  { id: 'sync-size',         name: 'Sync Size',          icon: '\uD83D\uDCCF',       category: 'sync',     panelPath: './panels/SyncSizePanel'          },
  { id: 'sync-debris',       name: 'Sync Debris',        icon: '\uD83D\uDDD1\uFE0F', category: 'sync',     panelPath: './panels/SyncDebrisPanel'        },
  { id: 'sync-restore',      name: 'Sync Restore',       icon: '\u267B\uFE0F',       category: 'sync',     panelPath: './panels/SyncRestorePanel'       },
  { id: 'desktop-sync',      name: 'Desktop Sync',       icon: '\uD83D\uDDA5\uFE0F', category: 'sync',     panelPath: './panels/DesktopSyncPanel'       },
  { id: 'desktop-support',   name: 'Desktop Support',    icon: '\uD83D\uDCBB',       category: 'sync',     panelPath: './panels/DesktopSupportPanel'    },
  { id: 'mobile-app',        name: 'Mobile App',         icon: '\uD83D\uDCF1',       category: 'sync',     panelPath: './panels/MobileAppPanel'         },

  // -- Backup & Recovery --
  { id: 'backup-job',        name: 'Backup Jobs',        icon: '\uD83D\uDCBE',       category: 'backup',   panelPath: './panels/BackupJobPanel'         },
  { id: 'backup-storage',    name: 'Backup Storage',     icon: '\uD83D\uDDC4\uFE0F', category: 'backup',   panelPath: './panels/BackupStoragePanel'     },
  { id: 'backup-policy',     name: 'Backup Policy',      icon: '\uD83D\uDCDC',       category: 'backup',   panelPath: './panels/BackupPolicyPanel'      },
  { id: 'backup-recovery',   name: 'Backup Recovery',    icon: '\uD83D\uDD04',       category: 'backup',   panelPath: './panels/BackupRecoveryPanel'    },
  { id: 'backup-notify',     name: 'Backup Notifications', icon: '\uD83D\uDD14',     category: 'backup',   panelPath: './panels/BackupNotifyPanel'      },
  { id: 'restore-delete',    name: 'Restore Deleted',    icon: '\u267B\uFE0F',       category: 'backup',   panelPath: './panels/RestoreDeletePanel'     },
  { id: 'rewind-action',     name: 'Rewind Action',      icon: '\u23EA',             category: 'backup',   panelPath: './panels/RewindActionPanel'      },
  { id: 'rewind-settings',   name: 'Rewind Settings',    icon: '\u2699\uFE0F',       category: 'backup',   panelPath: './panels/RewindSettingsPanel'    },
  { id: 'rubbish-bin',       name: 'Rubbish Bin',        icon: '\uD83D\uDDD1\uFE0F', category: 'backup',   panelPath: './panels/RubbishBinPanel'        },
  { id: 'version-history',   name: 'Version History',    icon: '\uD83D\uDD58',       category: 'backup',   panelPath: './panels/VersionHistoryPanel'    },
  { id: 'versioning-compare', name: 'Version Compare',   icon: '\uD83D\uDD0D',       category: 'backup',   panelPath: './panels/VersioningComparePanel' },
  { id: 'deleted-data',      name: 'Deleted Data',       icon: '\uD83D\uDCC9',       category: 'backup',   panelPath: './panels/DeletedDataPanel'       },
  { id: 'deletion-risk',     name: 'Deletion Risk',      icon: '\u26A0\uFE0F',       category: 'backup',   panelPath: './panels/DeletionRiskPanel'      },
  { id: 'data-deleted-by-mega', name: 'Data Deleted by Mega', icon: '\uD83D\uDEAB',  category: 'backup',   panelPath: './panels/DataDeletedByMegaPanel' },
  { id: 'undecrypted',       name: 'Undecrypted Files',  icon: '\uD83D\uDD13',       category: 'backup',   panelPath: './panels/UndecryptedPanel'       },

  // -- Account & Security --
  { id: 'account-overview',  name: 'Account Overview',   icon: '\uD83D\uDC64',       category: 'account',  panelPath: './panels/AccountOverviewPanel'   },
  { id: 'account-billing',   name: 'Account Billing',    icon: '\uD83D\uDCB3',       category: 'account',  panelPath: './panels/AccountBillingPanel'    },
  { id: 'account-security',  name: 'Account Security',   icon: '\uD83D\uDD12',       category: 'account',  panelPath: './panels/AccountSecurityPanel'   },
  { id: 'account-team',      name: 'Account Team',       icon: '\uD83D\uDC65',       category: 'account',  panelPath: './panels/AccountTeamPanel'       },
  { id: 'account-recovery',  name: 'Account Recovery',   icon: '\uD83D\uDD11',       category: 'account',  panelPath: './panels/AccountRecoveryPanel'   },
  { id: 'account-hacked',    name: 'Account Hacked',     icon: '\uD83D\uDEA8',       category: 'account',  panelPath: './panels/AccountHackedPanel'     },
  { id: 'credential-stuffing', name: 'Credential Stuffing', icon: '\uD83D\uDEE1\uFE0F', category: 'account', panelPath: './panels/CredentialStuffingPanel' },
  { id: 'suspended-account', name: 'Suspended Account',  icon: '\u26D4',             category: 'account',  panelPath: './panels/SuspendedAccountPanel'  },
  { id: 'start-over',        name: 'Start Over',         icon: '\uD83D\uDD04',       category: 'account',  panelPath: './panels/StartOverPanel'         },
  { id: 'keep-recovery-key', name: 'Recovery Key Safe',  icon: '\uD83D\uDD11',       category: 'account',  panelPath: './panels/KeepRecoveryKeySafePanel' },
  { id: 'resolve-2fa',       name: 'Resolve Two-Factor', icon: '\uD83D\uDD10',       category: 'account',  panelPath: './panels/ResolveTwoFactorAuthPanel' },
  { id: 'reset-pwd-email',   name: 'Reset Password',     icon: '\uD83D\uDCE7',       category: 'account',  panelPath: './panels/ResetPasswordAccessEmailPanel' },
  { id: 'encryption-info',   name: 'Encryption Info',    icon: '\uD83D\uDD10',       category: 'account',  panelPath: './panels/EncryptionInfoPanel'    },
  { id: 'secure-docs',       name: 'Secure Documents',   icon: '\uD83D\uDCC4',       category: 'account',  panelPath: './panels/SecureDocsPanel'        },
  { id: 'sso-connection',    name: 'SSO Connection',     icon: '\uD83D\uDD17',       category: 'account',  panelPath: './panels/SsoConnectionPanel'     },

  // -- Settings & Preferences --
  { id: 'profile-settings',  name: 'Profile Settings',   icon: '\uD83D\uDC64',       category: 'settings', panelPath: './panels/ProfileSettingsPanel'   },
  { id: 'profile-avatar',    name: 'Profile Avatar',     icon: '\uD83D\uDDBC\uFE0F', category: 'settings', panelPath: './panels/ProfileAvatarPanel'     },
  { id: 'settings-registry', name: 'Settings Registry',  icon: '\uD83D\uDCCB',       category: 'settings', panelPath: './panels/SettingsRegistryPanel'  },
  { id: 'locale-mgmt',       name: 'Locale Management',  icon: '\uD83C\uDF10',       category: 'settings', panelPath: './panels/LocaleMgmtPanel'       },
  { id: 'email-change',      name: 'Email Change',       icon: '\u2709\uFE0F',       category: 'settings', panelPath: './panels/EmailChangePanel'       },
  { id: 'email-notif',       name: 'Email Notifications', icon: '\uD83D\uDD14',      category: 'settings', panelPath: './panels/EmailNotifPanel'        },
  { id: 'notif-recents',     name: 'Notification Recents', icon: '\uD83D\uDCEC',     category: 'settings', panelPath: './panels/NotifRecentsPanel'      },
  { id: 'plan-quota',        name: 'Plan & Quota',       icon: '\uD83D\uDCCA',       category: 'settings', panelPath: './panels/PlanQuotaPanel'         },
  { id: 'transfer-quota',    name: 'Transfer Quota',     icon: '\uD83D\uDCE4',       category: 'settings', panelPath: './panels/TransferQuotaPanel'     },
  { id: 'transfer-speed',    name: 'Transfer Speed',     icon: '\u26A1',             category: 'settings', panelPath: './panels/TransferSpeedPanel'     },
  { id: 'login-config',      name: 'Login Config',       icon: '\uD83D\uDD11',       category: 'settings', panelPath: './panels/LoginConfigPanel'       },
  { id: 'password-manager',  name: 'Password Manager',   icon: '\uD83D\uDD10',       category: 'settings', panelPath: './panels/PasswordManagerPanel'   },
  { id: 'download',          name: 'Downloads',          icon: '\u2B07\uFE0F',       category: 'settings', panelPath: './panels/DownloadPanel'          },
  { id: 'download-location', name: 'Download Location',  icon: '\uD83D\uDCC2',       category: 'settings', panelPath: './panels/DownloadLocationPanel'  },
  { id: 'download-finder',   name: 'Download Finder',    icon: '\uD83D\uDD0E',       category: 'settings', panelPath: './panels/DownloadFinderPanel'    },

  // -- Help & Troubleshooting --
  { id: 'help-center',       name: 'Help Center',        icon: '\u2753',             category: 'help',     panelPath: './panels/HelpCenterPanel'        },
  { id: 'loading-perf',      name: 'Loading Performance', icon: '\u26A1',            category: 'help',     panelPath: './panels/LoadingPerfPanel'       },
  { id: 'loading-times',     name: 'Loading Times',      icon: '\u23F1\uFE0F',       category: 'help',     panelPath: './panels/LoadingTimesPanel'      },
  { id: 'page-diagnostics',  name: 'Page Diagnostics',   icon: '\uD83D\uDCDF',       category: 'help',     panelPath: './panels/PageDiagnosticsPanel'   },
  { id: 'link-diagnostics',  name: 'Link Diagnostics',   icon: '\uD83D\uDD17',       category: 'help',     panelPath: './panels/LinkDiagnosticsPanel'   },
  { id: 'browser-compat',    name: 'Browser Compatibility', icon: '\uD83C\uDF10',    category: 'help',     panelPath: './panels/BrowserCompatPanel'     },
  { id: 'browser-limits',    name: 'Browser Limits',     icon: '\uD83D\uDEA7',       category: 'help',     panelPath: './panels/BrowserLimitsPanel'     },
  { id: 'browser-requirements', name: 'Browser Requirements', icon: '\uD83D\uDCCB',  category: 'help',     panelPath: './panels/BrowserRequirementsPanel' },
  { id: 'login-issues',      name: 'Login Issues',       icon: '\uD83D\uDEAA',       category: 'help',     panelPath: './panels/LoginIssuesPanel'       },
  { id: 'login-troubleshoot', name: 'Login Troubleshoot', icon: '\uD83D\uDD27',      category: 'help',     panelPath: './panels/LoginTroubleshootPanel' },
  { id: 'incorrect-password', name: 'Incorrect Password', icon: '\u274C',            category: 'help',     panelPath: './panels/IncorrectPasswordPanel' },
  { id: 'forgot-password',   name: 'Forgot Password',    icon: '\uD83E\uDD14',       category: 'help',     panelPath: './panels/ForgotPasswordPanel'    },
  { id: 'forgot-email',      name: 'Forgot Email Address', icon: '\u2709\uFE0F',     category: 'help',     panelPath: './panels/ForgotEmailAddressPanel' },
  { id: 'no-email-received', name: 'No Email Received',  icon: '\uD83D\uDCED',       category: 'help',     panelPath: './panels/DidNotReceiveEmailPanel' },
  { id: 'isp-blocking',      name: 'ISP Blocking',       icon: '\uD83D\uDEAB',       category: 'help',     panelPath: './panels/IspBlockingMegaPanel'   },
  { id: 'reload-account',    name: 'Reload Account',     icon: '\uD83D\uDD04',       category: 'help',     panelPath: './panels/ReloadAccountPanel'     },
  { id: 'transfer-error',    name: 'Transfer Error',     icon: '\u26A0\uFE0F',       category: 'help',     panelPath: './panels/TransferErrorPanel'     },
  { id: 'drive-dashboard',   name: 'Drive Dashboard',    icon: '\uD83D\uDCBE',       category: 'help',     panelPath: './panels/DriveDashboardPanel'    },
  { id: 'notifications-recents', name: 'Notifications', icon: '\uD83D\uDD14',       category: 'help',     panelPath: './panels/NotificationsRecentsPanel' },
]

/**
 * Search features by name (case-insensitive)
 */
export function searchFeatures(query) {
  if (!query) return FEATURES
  const q = query.toLowerCase()
  return FEATURES.filter(f =>
    f.name.toLowerCase().includes(q) ||
    f.id.toLowerCase().includes(q)
  )
}
