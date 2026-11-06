import { NavLink, matchPath, useLocation } from 'react-router-dom';
import {
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import DashboardIcon from '@mui/icons-material/Dashboard';
import SettingsIcon from '@mui/icons-material/Settings';

const menuItems = [
  { text: 'Providers', icon: <DashboardIcon />, path: '/admin' },
  { text: 'Settings', icon: <SettingsIcon />, path: '/admin/settings' },
];

export default function Sidebar() {
  const { pathname } = useLocation();
  return (
    <List>
      {menuItems.map((item) => {
        const isSelected = !!matchPath({ path: item.path, end: true }, pathname);
        return (
          <ListItem key={item.text} disablePadding>
            <ListItemButton
              component={NavLink}
              to={item.path}
              end
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
