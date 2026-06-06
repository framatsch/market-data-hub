import { NavLink, useMatch } from 'react-router-dom';
import {
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import DashboardIcon from '@mui/icons-material/Dashboard';
import SettingsInputComponentIcon from '@mui/icons-material/SettingsInputComponent';
import KeyIcon from '@mui/icons-material/Key';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import NotificationsIcon from '@mui/icons-material/Notifications';
import SettingsIcon from '@mui/icons-material/Settings';

const menuItems = [
  { text: 'Dashboard', icon: <DashboardIcon />, path: '/admin' },
  { text: 'Providers', icon: <SettingsInputComponentIcon />, path: '/admin/providers' },
  { text: 'Credentials', icon: <KeyIcon />, path: '/admin/credentials' },
  { text: 'Schwab Auth', icon: <AccountBalanceIcon />, path: '/admin/schwab-auth' },
  { text: 'Alerts', icon: <NotificationsIcon />, path: '/admin/alerts' },
  { text: 'Settings', icon: <SettingsIcon />, path: '/admin/settings' },
];

export default function Sidebar() {
  return (
    <List>
      {menuItems.map((item) => {
        const isSelected = !!useMatch(item.path);
        return (
          <ListItem key={item.text} disablePadding>
            <ListItemButton
              component={NavLink}
              to={item.path}
              selected={isSelected}
              sx={{
                '&.active': {
                  bgcolor: 'action.selected',
                },
              }}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.text} />
            </ListItemButton>
          </ListItem>
        );
      })}
    </List>
  );
}
