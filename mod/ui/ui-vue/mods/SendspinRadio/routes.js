// Route record. The Vue record carries the live component object, which is what
// lets a real .vue SFC render inside a mod.

import RadioScreen from "./views/RadioScreen.vue"

export const ROUTE_SOURCE_ID = "SendspinRadio.routes"

export const ROUTE_NAME = "sendspinRadio.full"

export const routeRecords = [
  {
    path: "/menu/sendspin-radio",
    name: ROUTE_NAME,
    component: RadioScreen,
    meta: {
      luaRoute: {
        title: "Sendspin Radio",
        backTarget: "menu",
        scopeTree: { "sendspin-radio-route": {} },
      },
    },
  },
]
