CREATE MIGRATION m1juuapt4uhhzfoclhapnb7jxdc2t2tmoi6nbg6lu4si67n7qwnknq
    ONTO m1fcj22bmvt4u3zo6x76lcp6s7khw4gyrvplbkdob6kaffz2yagvca
{
  CREATE SCALAR TYPE userProfile::RiskAppetite EXTENDING std::int16 {
      CREATE CONSTRAINT std::max_value(5);
      CREATE CONSTRAINT std::min_value(1);
  };
};
