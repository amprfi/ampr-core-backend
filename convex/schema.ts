import { defineSchema } from "convex/server";
import { users } from "./tables/users";
import { assets } from "./tables/assets";
import { profiles } from "./tables/profiles";
import { portfolioItems } from "./tables/portfolioItems";
import { chats, messages, summaries } from "./tables/messaging";
import { modules } from "./tables/modules";
import { notificationTypes, notificationPreferences, notificationQueue } from "./tables/notifications";
import { countries } from "./tables/countries";

export default defineSchema({
  users,
  assets,
  profiles,
  portfolioItems,
  chats,
  messages,
  summaries,
  modules,
  notificationTypes,
  notificationPreferences,
  notificationQueue,
  countries,
});
