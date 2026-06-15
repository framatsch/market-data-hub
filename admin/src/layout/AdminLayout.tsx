import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import {
  Box,
  Drawer,
  AppBar,
  Toolbar,
  Typography,
  Divider,
  IconButton,
  Container,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Link,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import GitHubIcon from '@mui/icons-material/GitHub';
import Sidebar from './Sidebar';

const drawerWidth = 240;
const logoUrl = '/admin/logo.svg';

export default function AdminLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const handleOpenAbout = () => {
    setAboutOpen(true);
  };

  const handleCloseAbout = () => {
    setAboutOpen(false);
  };

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar
        position="fixed"
        sx={{
          zIndex: (theme) => theme.zIndex.drawer + 1,
        }}
      >
        <Toolbar>
          <IconButton
            color="inherit"
            aria-label="open drawer"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2, display: { sm: 'none' } }}
          >
            <MenuIcon />
          </IconButton>
          
          <Box
            component="img"
            src={logoUrl}
            alt="Market Data Hub Logo"
            onClick={handleOpenAbout}
            sx={{
              height: 32,
              width: 32,
              mr: 2,
              cursor: 'pointer',
              borderRadius: '4px',
              transition: 'transform 0.2s',
              '&:hover': {
                transform: 'scale(1.1)',
              },
            }}
          />

          <Typography
            variant="h6"
            noWrap
            component="div"
            onClick={handleOpenAbout}
            sx={{
              cursor: 'pointer',
              '&:hover': {
                opacity: 0.85,
              },
            }}
          >
            Market Data Hub Admin
          </Typography>
        </Toolbar>
      </AppBar>
      <Box
        component="nav"
        sx={{ width: { sm: drawerWidth }, flexShrink: { sm: 0 } }}
      >
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{
            keepMounted: true, // Better open performance on mobile.
          }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth },
          }}
        >
          <Toolbar />
          <Divider />
          <Sidebar />
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth },
          }}
          open
        >
          <Toolbar />
          <Divider />
          <Sidebar />
        </Drawer>
      </Box>
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: { sm: `calc(100% - ${drawerWidth}px)` },
        }}
      >
        <Toolbar />
        <Container maxWidth="lg">
          <Outlet />
        </Container>
      </Box>

      {/* About Dialog */}
      <Dialog
        open={aboutOpen}
        onClose={handleCloseAbout}
        maxWidth="xs"
        fullWidth
      >
        <Box sx={{ p: 2 }}>
          <DialogTitle sx={{ textAlign: 'center', pb: 1 }}>
            About Market Data Hub
          </DialogTitle>
          <DialogContent sx={{ textAlign: 'center', pb: 2 }}>
            <Box
              component="img"
              src={logoUrl}
              alt="Market Data Hub Logo"
              sx={{
                height: 80,
                width: 80,
                mx: 'auto',
                my: 2,
                display: 'block',
                borderRadius: '8px',
                boxShadow: '0 4px 20px rgba(0,255,255,0.15)',
              }}
            />
            <Typography variant="h6" gutterBottom>
              Market Data Hub Admin
            </Typography>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              Version 1.0.0
            </Typography>
            <Typography variant="body2" sx={{ mt: 2, mb: 3, px: 2 }}>
              FastAPI data service and administration panel for real-time and historical market data.
            </Typography>
            <Divider sx={{ my: 2 }} />
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, alignItems: 'center' }}>
              <Button
                component="a"
                variant="outlined"
                color="primary"
                startIcon={<GitHubIcon />}
                href="https://github.com/scheffold/market-data-hub"
                target="_blank"
                rel="noopener noreferrer"
                fullWidth
                sx={{ textTransform: 'none' }}
              >
                GitHub Repository
              </Button>
              <Typography variant="caption" color="text.secondary">
                License:{' '}
                <Link
                  href="https://github.com/scheffold/market-data-hub/blob/main/LICENSE"
                  target="_blank"
                  rel="noopener noreferrer"
                  color="inherit"
                  underline="always"
                >
                  AGPL-3.0-or-later
                </Link>
              </Typography>
            </Box>
          </DialogContent>
          <DialogActions sx={{ justifyContent: 'center', pb: 1 }}>
            <Button onClick={handleCloseAbout} variant="contained" color="primary">
              Close
            </Button>
          </DialogActions>
        </Box>
      </Dialog>
    </Box>
  );
}
